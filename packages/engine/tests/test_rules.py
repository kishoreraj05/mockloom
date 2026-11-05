import json
from pathlib import Path

import pytest
from mockforge_engine import Rule
from mockforge_engine.rules import CompiledRule, RequestView
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]


def view(**kwargs):
    defaults = dict(method="GET", url="/", path={}, query={}, headers={}, cookies={}, body=None)
    return RequestView(**{**defaults, **kwargs})


def rule(*conditions, mode="all"):
    return CompiledRule(
        "r", Rule(name="r", route="GET /x", when={mode: list(conditions)}, then={"status": 200})
    )


def cond(source, field, op, value=None):
    return {"source": source, "field": field, "op": op, "value": value}


@pytest.mark.parametrize(
    "condition, request_kwargs, expected",
    [
        (cond("query", "s", "eq", "a"), {"query": {"s": "a"}}, True),
        (cond("query", "s", "eq", "a"), {"query": {"s": "b"}}, False),
        (cond("query", "s", "eq", "a"), {}, False),
        (cond("path", "id", "eq", "42"), {"path": {"id": 42}}, True),  # loose across types
        (cond("query", "b", "eq", True), {"query": {"b": "true"}}, True),
        (cond("query", "s", "neq", "a"), {"query": {"s": "b"}}, True),
        (cond("query", "s", "neq", "a"), {}, True),
        (cond("header", "X-Tier", "in", ["free", "trial"]), {"headers": {"x-tier": "free"}}, True),
        (cond("header", "X-Tier", "in", ["free"]), {"headers": {"x-tier": "pro"}}, False),
        (cond("cookie", "c", "exists"), {"cookies": {"c": "1"}}, True),
        (cond("cookie", "c", "exists"), {}, False),
        (cond("cookie", "c", "exists", False), {}, True),
        (cond("query", "s", "contains", "ell"), {"query": {"s": "hello"}}, True),
        (cond("query", "s", "contains", "b"), {"query": {"s": ["a", "b"]}}, True),
        (cond("body", "$.o", "contains", "k"), {"body": {"o": {"k": 1}}}, True),
        (cond("query", "s", "regex", "^h.+o$"), {"query": {"s": "hello"}}, True),
        (cond("query", "n", "gt", 5), {"query": {"n": "6"}}, True),
        (cond("query", "n", "lt", 5), {"query": {"n": "6"}}, False),
        (cond("query", "n", "gt", 5), {"query": {"n": "abc"}}, False),
        (cond("body", "$.items[0].sku", "eq", "A"), {"body": {"items": [{"sku": "A"}]}}, True),
        (cond("body", "items[0].sku", "eq", "A"), {"body": {"items": [{"sku": "A"}]}}, True),
        (cond("body", "$.missing", "exists"), {"body": {"a": 1}}, False),
        (cond("body", "$.a", "exists"), {}, False),
        (
            cond("body", "$", "matches_schema", {"type": "object", "required": ["a"]}),
            {"body": {"a": 1}},
            True,
        ),
        (
            cond("body", "$", "matches_schema", {"type": "object", "required": ["a"]}),
            {"body": {"b": 1}},
            False,
        ),
    ],
)
def test_operators(condition, request_kwargs, expected):
    assert rule(condition).matches(view(**request_kwargs)) is expected


def test_all_and_any():
    a, b = cond("query", "a", "exists"), cond("query", "b", "exists")
    assert not rule(a, b).matches(view(query={"a": "1"}))
    assert rule(a, b, mode="any").matches(view(query={"a": "1"}))


def test_no_conditions_always_matches():
    assert CompiledRule("r", Rule(name="r", route="GET /x")).matches(view())


def test_catastrophic_regex_gives_up_instead_of_hanging():
    request = view(query={"s": "a" * 64 + "!"})
    compiled = rule(cond("query", "s", "regex", "^(a|a)*$"))
    assert compiled.matches(request) is False
    assert any("timed out" in note for note in request.notes)


@pytest.mark.parametrize(
    "bad",
    [
        {"when": {"all": [cond("query", "s", "in", "not-a-list")]}},
        {"when": {"all": [cond("query", "s", "regex", "(")]}},
        {"when": {"all": [cond("query", "s", "gt", "abc")]}},
        {"when": {"all": [cond("query", "s", "matches_schema", {"type": "nope"})]}},
        {"when": {"all": [cond("body", "$..[", "eq", 1)]}},
        {"when": {"all": [cond("bogus", "s", "eq", 1)]}},
        {"when": {"all": [cond("query", "s", "bogus", 1)]}},
        {"when": {"all": [], "any": []}},
        {"then": {"status": 999}},
        {"then": {"delay_ms": 60_001}},
        {"then": {"statuss": 200}},
        {"then": {"body": "{{ 9**9 }}"}},
        {"then": {"headers": {"x": "{{ nope }}"}}},
        {"then": {"body": "x" * (1024 * 1024 + 1)}},
    ],
)
def test_invalid_rules_are_rejected(bad):
    with pytest.raises(ValidationError):
        Rule(name="r", route="GET /x", **bad)


def test_example_rules_are_valid():
    paths = sorted((ROOT / "examples" / "rules" / "petstore").glob("*.json"))
    assert len(paths) == 10
    for path in paths:
        Rule.model_validate(json.loads(path.read_text()))


def test_published_schema_is_current():
    from mockforge_engine import rule_json_schema

    published = json.loads((ROOT / "packages" / "engine" / "rule.schema.json").read_text())
    assert published == json.loads(json.dumps(rule_json_schema()))
