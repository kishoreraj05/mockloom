import time

BAD_SPEC = "openapi: 3.0.3\ninfo:\n  title: [unclosed\n"
ONE_ROUTE = """
openapi: 3.0.3
info: {title: Small, version: '1'}
paths:
  /only:
    get:
      responses:
        '200': {description: ok}
"""


def rule_payload(**overrides):
    return {"name": "R", "route": "GET /pets", "then": {"status": 200, "body": {"ok": True}}, **overrides}


class TestWorkspaces:
    def test_slug_conflict(self, client, workspace):
        response = client.post("/api/workspaces", json={"name": "X", "slug": workspace})
        assert response.status_code == 409

    def test_auto_slug_is_unique(self, client):
        base = f"same-{time.time_ns()}"
        first = client.post("/api/workspaces", json={"name": base}).json()
        second = client.post("/api/workspaces", json={"name": base}).json()
        assert first["slug"] != second["slug"]
        client.delete(f"/api/workspaces/{first['slug']}")
        client.delete(f"/api/workspaces/{second['slug']}")

    def test_bad_slug(self, client):
        assert client.post("/api/workspaces", json={"name": "X", "slug": "Bad Slug!"}).status_code == 422

    def test_bad_spec_creates_nothing(self, client):
        slug = f"bad-{time.time_ns()}"
        response = client.post("/api/workspaces", json={"name": "X", "slug": slug, "spec_text": BAD_SPEC})
        assert response.status_code == 422
        assert response.json()["detail"]["issues"][0]["line"] is not None
        assert client.get(f"/api/workspaces/{slug}").status_code == 404

    def test_workspace_without_spec(self, client):
        slug = f"empty-{time.time_ns()}"
        client.post("/api/workspaces", json={"name": "X", "slug": slug})
        assert client.get(f"/api/workspaces/{slug}/routes").json() == []
        assert client.get(f"/mock/{slug}/anything").status_code == 404
        client.delete(f"/api/workspaces/{slug}")

    def test_delete_removes_everything(self, client, petstore_text):
        slug = f"gone-{time.time_ns()}"
        client.post("/api/workspaces", json={"name": "X", "slug": slug, "spec_text": petstore_text})
        client.post(f"/api/workspaces/{slug}/rules", json=rule_payload())
        client.get(f"/mock/{slug}/pets")
        assert client.delete(f"/api/workspaces/{slug}").status_code == 204
        assert client.get(f"/mock/{slug}/pets").status_code == 404

    def test_seed_change_changes_output(self, client, workspace):
        before = client.get(f"/mock/{workspace}/pets/1").json()
        assert client.get(f"/mock/{workspace}/pets/1").json() == before
        client.patch(f"/api/workspaces/{workspace}", json={"seed": 999})
        assert client.get(f"/mock/{workspace}/pets/1").json() != before

    def test_validation_can_be_turned_off(self, client, workspace):
        url = f"/mock/{workspace}/pets?limit=abc"
        assert client.get(url).status_code == 400
        client.patch(f"/api/workspaces/{workspace}", json={"validation_mode": "off"})
        assert client.get(url).status_code == 200


class TestSpecVersions:
    def test_validate_does_not_save(self, client, workspace):
        response = client.post("/api/specs/validate", json={"text": ONE_ROUTE})
        assert response.json()["ok"] and response.json()["route_count"] == 1
        assert client.get(f"/mock/{workspace}/pets").status_code == 200

    def test_reload_takes_effect_without_restart(self, client, workspace):
        saved = client.put(f"/api/workspaces/{workspace}/spec", json={"text": ONE_ROUTE})
        assert saved.status_code == 200 and saved.json()["version"] == 2
        assert client.get(f"/mock/{workspace}/only").status_code == 200
        assert client.get(f"/mock/{workspace}/pets").status_code == 404

    def test_same_text_is_not_a_new_version(self, client, workspace, petstore_text):
        saved = client.put(f"/api/workspaces/{workspace}/spec", json={"text": petstore_text}).json()
        assert saved["changed"] is False and saved["version"] == 1

    def test_versions_are_kept(self, client, workspace):
        client.put(f"/api/workspaces/{workspace}/spec", json={"text": ONE_ROUTE})
        versions = client.get(f"/api/workspaces/{workspace}/spec/versions").json()
        assert [v["version"] for v in versions] == [2, 1]
        assert versions[0]["active"] and not versions[1]["active"]
        assert client.get(f"/api/workspaces/{workspace}/spec").json()["text"] == ONE_ROUTE

    def test_bad_spec_keeps_the_old_one_serving(self, client, workspace):
        assert client.put(f"/api/workspaces/{workspace}/spec", json={"text": BAD_SPEC}).status_code == 422
        assert client.get(f"/mock/{workspace}/pets").status_code == 200

    def test_dropped_route_orphans_rules_and_restoring_recovers_them(
        self, client, workspace, petstore_text
    ):
        client.post(f"/api/workspaces/{workspace}/rules", json=rule_payload())
        saved = client.put(f"/api/workspaces/{workspace}/spec", json={"text": ONE_ROUTE}).json()
        assert saved["orphaned_rules"] == ["R"]
        rules = client.get(f"/api/workspaces/{workspace}/rules").json()
        assert len(rules) == 1 and rules[0]["orphaned"]

        restored = client.put(f"/api/workspaces/{workspace}/spec", json={"text": petstore_text}).json()
        assert restored["restored_rules"] == ["R"]
        assert client.get(f"/mock/{workspace}/pets").json() == {"ok": True}


class TestRoutes:
    def test_list_has_counts(self, client, workspace):
        client.post(f"/api/workspaces/{workspace}/rules", json=rule_payload())
        routes = {r["key"]: r for r in client.get(f"/api/workspaces/{workspace}/routes").json()}
        assert routes["GET /pets"]["rule_count"] == 1 and routes["GET /pets"]["tag"] == "pets"

    def test_detail(self, client, workspace):
        detail = client.get(f"/api/workspaces/{workspace}/routes/detail", params={"key": "POST /pets"}).json()
        assert detail["body_required"] and detail["body_content_types"] == ["application/json"]
        assert "name" in detail["sample_body"]
        assert {r["status"] for r in detail["responses"]} == {"201", "400"}

    def test_sample_for_status(self, client, workspace):
        sample = client.get(
            f"/api/workspaces/{workspace}/routes/sample", params={"key": "GET /pets/{id}", "status": "404"}
        ).json()
        assert sample["status"] == "404" and "message" in sample["body"]
        assert "components" in sample["schema"]

    def test_unknown_route(self, client, workspace):
        response = client.get(f"/api/workspaces/{workspace}/routes/detail", params={"key": "GET /nope"})
        assert response.status_code == 404


class TestRules:
    def test_crud_applies_immediately(self, client, workspace):
        base = f"/api/workspaces/{workspace}/rules"
        created = client.post(base, json=rule_payload()).json()
        assert client.get(f"/mock/{workspace}/pets").json() == {"ok": True}

        updated = client.put(f"{base}/{created['id']}", json=rule_payload(then={"body": {"ok": False}}))
        assert updated.status_code == 200
        assert client.get(f"/mock/{workspace}/pets").json() == {"ok": False}

        client.put(f"{base}/{created['id']}", json=rule_payload(enabled=False))
        assert "items" in client.get(f"/mock/{workspace}/pets").json()

        assert client.delete(f"{base}/{created['id']}").status_code == 204
        assert client.get(base).json() == []

    def test_status_only_rule_survives_storage(self, client, workspace):
        client.post(
            f"/api/workspaces/{workspace}/rules",
            json=rule_payload(route="GET /pets/{id}", then={"status": 404}),
        )
        response = client.get(f"/mock/{workspace}/pets/1")
        assert response.status_code == 404 and "message" in response.json()

    def test_rule_for_unknown_route_is_refused(self, client, workspace):
        response = client.post(f"/api/workspaces/{workspace}/rules", json=rule_payload(route="GET /nope"))
        assert response.status_code == 422

    def test_dangerous_template_is_refused(self, client, workspace):
        response = client.post(
            f"/api/workspaces/{workspace}/rules", json=rule_payload(then={"body": "{{ 9**9**9 }}"})
        )
        assert response.status_code == 422

    def test_rules_of_other_workspaces_are_out_of_reach(self, client, workspace):
        rule_id = client.post(f"/api/workspaces/{workspace}/rules", json=rule_payload()).json()["id"]
        other = f"other-{time.time_ns()}"
        client.post("/api/workspaces", json={"name": "Other", "slug": other})
        assert client.delete(f"/api/workspaces/{other}/rules/{rule_id}").status_code == 404
        client.delete(f"/api/workspaces/{other}")


class TestChaosApi:
    def test_global_and_route_scopes(self, client, workspace):
        base = f"/api/workspaces/{workspace}/chaos"
        client.put(base, json={"forced_status": 503})
        assert client.get(f"/mock/{workspace}/pets").status_code == 503
        client.put(base, json={"route_key": "GET /pets"})
        assert client.get(f"/mock/{workspace}/pets").status_code == 200
        assert client.get(f"/mock/{workspace}/pets/1").status_code == 503
        assert len(client.get(base).json()) == 2

    def test_put_replaces_rather_than_duplicates(self, client, workspace):
        base = f"/api/workspaces/{workspace}/chaos"
        client.put(base, json={"forced_status": 503})
        client.put(base, json={"forced_status": 500})
        assert len(client.get(base).json()) == 1

    def test_clear(self, client, workspace):
        base = f"/api/workspaces/{workspace}/chaos"
        client.put(base, json={"forced_status": 503})
        client.delete(base)
        assert client.get(f"/mock/{workspace}/pets").status_code == 200

    def test_latency_is_really_applied(self, client, workspace):
        client.put(f"/api/workspaces/{workspace}/chaos", json={"latency_min_ms": 120})
        started = time.perf_counter()
        client.get(f"/mock/{workspace}/pets")
        assert time.perf_counter() - started >= 0.12
        entry = client.get(f"/api/workspaces/{workspace}/logs").json()[-1]
        assert entry["duration_ms"] >= 120 and entry["overhead_ms"] < 120

    def test_limits(self, client, workspace):
        base = f"/api/workspaces/{workspace}/chaos"
        assert client.put(base, json={"latency_max_ms": 60_001}).status_code == 422
        assert client.put(base, json={"error_rate": 1.5}).status_code == 422
        assert client.put(base, json={"latency_min_ms": 10, "latency_max_ms": 5}).status_code == 422

    def test_offline_without_a_real_socket_falls_back_to_503(self, client, workspace):
        client.put(f"/api/workspaces/{workspace}/chaos", json={"offline": True})
        assert client.get(f"/mock/{workspace}/pets").status_code == 503
        entry = client.get(f"/api/workspaces/{workspace}/logs").json()[-1]
        assert entry["status"] == 0 and "offline" in entry["chaos"]


class TestMockHttp:
    def test_cors_preflight_for_app_on_another_origin(self, client, workspace):
        response = client.options(
            f"/mock/{workspace}/pets",
            headers={
                "origin": "http://localhost:3000",
                "access-control-request-method": "POST",
                "access-control-request-headers": "x-user-tier",
            },
        )
        assert response.status_code == 204
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
        assert response.headers["access-control-allow-headers"] == "x-user-tier"
        # Preflights are browser plumbing, not requests the user made.
        assert client.get(f"/api/workspaces/{workspace}/logs").json() == []

    def test_cors_on_normal_response_and_errors(self, client, workspace):
        headers = {"origin": "http://localhost:3000"}
        for url in (f"/mock/{workspace}/pets", f"/mock/{workspace}/nope", "/mock/no-such-workspace/x"):
            assert client.get(url, headers=headers).headers["access-control-allow-origin"]

    def test_management_api_is_not_cors_enabled(self, client, workspace):
        response = client.get(f"/api/workspaces/{workspace}", headers={"origin": "https://evil.example"})
        assert "access-control-allow-origin" not in response.headers

    def test_url_with_a_newline_still_reaches_the_mock(self, client, workspace):
        response = client.get(f"/mock/{workspace}/pets/abc%0Ad")
        assert response.status_code == 400 and response.json()["title"] == "Request does not match the spec"
        assert "access-control-allow-origin" in client.get(f"/mock/{workspace}/nope%0Ax").headers
        paths = [entry["path"] for entry in client.get(f"/api/workspaces/{workspace}/logs").json()]
        assert "/pets/abc\nd" in paths

    def test_unknown_workspace(self, client):
        assert client.get("/mock/no-such-workspace/x").json()["title"] == "No such workspace"

    def test_body_limit(self, client, workspace):
        response = client.post(
            f"/mock/{workspace}/pets",
            content=b"x" * (5 * 1024 * 1024 + 1),
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 413

    def test_secrets_are_not_logged(self, client, workspace):
        client.get(
            f"/mock/{workspace}/pets",
            headers={"authorization": "Bearer real-token", "cookie": "session=real", "x-api-key": "real"},
        )
        entry = client.get(f"/api/workspaces/{workspace}/logs").json()[-1]
        assert "real" not in str(entry["request"]["headers"])

    def test_rule_can_still_read_redacted_values(self, client, workspace):
        client.post(
            f"/api/workspaces/{workspace}/rules",
            json=rule_payload(
                when={"all": [{"source": "cookie", "field": "role", "op": "eq", "value": "admin"}]}
            ),
        )
        response = client.get(f"/mock/{workspace}/pets", headers={"cookie": "role=admin"})
        assert response.json() == {"ok": True}

    def test_head_is_refused_when_the_spec_does_not_declare_it(self, client, workspace):
        assert client.head(f"/mock/{workspace}/pets").status_code == 405

    def test_rate_limit(self, settings, petstore_text):
        from dataclasses import replace

        from fastapi.testclient import TestClient
        from mockforge_api.main import create_app

        limited = replace(settings, rate_limit_per_minute=2)
        with TestClient(create_app(limited)) as client:
            slug = f"rate-{time.time_ns()}"
            client.post("/api/workspaces", json={"name": "R", "slug": slug, "spec_text": petstore_text})
            codes = [client.get(f"/mock/{slug}/pets").status_code for _ in range(4)]
            assert codes[:2] == [200, 200] and 429 in codes[2:]
            client.delete(f"/api/workspaces/{slug}")
