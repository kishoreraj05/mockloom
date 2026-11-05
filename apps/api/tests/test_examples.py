"""The examples in the gallery are promises to new users, so every one of them is exercised here."""

import json
import os
import random
from pathlib import Path

import pytest
from mockforge_engine import Generator, Rule, validate_text
from mockforge_engine.schema import collect_errors

ROOT = Path(__file__).resolve().parents[3] / "examples"
CATALOG = json.loads((ROOT / "catalog.json").read_text())
ids = [example["id"] for example in CATALOG]


def spec_text(example):
    return (ROOT / "specs" / f"{example['id']}.yaml").read_text()


def rules_of(example):
    return [json.loads(p.read_text()) for p in sorted((ROOT / "rules" / example["id"]).glob("*.json"))]


@pytest.fixture(params=CATALOG, ids=ids)
def example(request):
    return request.param


def test_nothing_in_the_folders_is_left_out_of_the_catalog():
    assert sorted(p.stem for p in (ROOT / "specs").glob("*.yaml")) == sorted(ids)
    assert sorted(p.name for p in (ROOT / "rules").iterdir() if p.is_dir()) == sorted(ids)


def test_catalog_facts_are_true_and_the_spec_is_clean(example):
    report = validate_text(spec_text(example))
    assert report.ok
    assert report.issues == []  # An example people copy should have no warnings at all.
    assert report.route_count == example["routes"]
    assert report.openapi_version.startswith(example["openapi"])
    assert report.title == example["name"]


def test_rules_target_real_routes(example):
    report = validate_text(spec_text(example))
    rules = rules_of(example)
    assert rules
    for raw in rules:
        assert Rule.model_validate(raw).route in report.spec.routes


def test_generated_responses_match_their_own_schemas(example):
    spec = validate_text(spec_text(example)).spec
    for route in spec.routes.values():
        for response in route.responses.values():
            for media in response.content:
                value = Generator(spec.context, random.Random(1)).generate(media.schema)
                assert collect_errors(spec.context.validator(media.schema), value, 3) == [], route.key


def test_every_listed_scenario_does_what_it_says(client, example):
    slug = f"{example['id']}-{os.getpid()}"
    created = client.post(
        "/api/workspaces",
        json={"name": example["name"], "slug": slug, "spec_text": spec_text(example), "rules": rules_of(example)},
    )
    assert created.status_code == 201, created.text
    assert created.json()["rule_count"] == len(rules_of(example))

    rules_seen = set()
    for scenario in example["try"]:
        response = client.request(
            scenario["method"],
            f"/mock/{slug}{scenario['path']}",
            params=scenario.get("query"),
            headers=scenario.get("headers"),
            json=scenario.get("body"),
        )
        label = scenario["label"]
        assert response.status_code == scenario["expect_status"], f"{label}: {response.text}"
        assert response.headers.get("x-mockforge-rule") == scenario["expect_rule"], label
        rules_seen.add(scenario["expect_rule"])
    assert len(rules_seen) >= 3  # The list has to actually demonstrate rules.
    client.delete(f"/api/workspaces/{slug}")


def test_sample_values_shown_for_every_route_pass_validation(client, example):
    """The UI offers these as copy-paste requests, so none may be rejected by the mock's own validation."""
    slug = f"samples-{example['id']}-{os.getpid()}"
    client.post("/api/workspaces", json={"name": example["name"], "slug": slug, "spec_text": spec_text(example)})
    for summary in client.get(f"/api/workspaces/{slug}/routes").json():
        detail = client.get(f"/api/workspaces/{slug}/routes/detail", params={"key": summary["key"]}).json()
        path, query, headers = detail["path"], {}, {}
        for parameter in detail["parameters"]:
            value = str(parameter["example"])
            if parameter["location"] == "path":
                path = path.replace("{" + parameter["name"] + "}", value)
            elif parameter["required"] and parameter["location"] == "query":
                query[parameter["name"]] = value
            elif parameter["required"] and parameter["location"] == "header":
                headers[parameter["name"]] = value
        response = client.request(
            detail["method"], f"/mock/{slug}{path}", params=query, headers=headers, json=detail["sample_body"]
        )
        assert response.status_code != 400, f"{summary['key']}: {response.text}"
    client.delete(f"/api/workspaces/{slug}")


def test_creating_with_a_bad_rule_creates_nothing(client, petstore_text):
    slug = f"atomic-{os.getpid()}"
    bad = {"name": "R", "route": "GET /nope", "then": {"status": 200}}
    body = {"name": "A", "slug": slug, "spec_text": petstore_text, "rules": [bad]}
    response = client.post("/api/workspaces", json=body)
    assert response.status_code == 422
    assert client.get(f"/api/workspaces/{slug}").status_code == 404


def test_rules_without_a_spec_are_refused(client):
    bad = {"name": "R", "route": "GET /x", "then": {"status": 200}}
    assert client.post("/api/workspaces", json={"name": "A", "rules": [bad]}).status_code == 422
