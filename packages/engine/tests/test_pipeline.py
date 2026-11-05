import json
import random
import time
from pathlib import Path

import pytest
from mockforge_engine import ChaosConfig, MockEngine, RawRequest, Rule, compile_spec

ROOT = Path(__file__).resolve().parents[3]


def get(path, **kwargs):
    return RawRequest("GET", path, **kwargs)


def post_json(path, payload):
    return RawRequest(
        "POST", path, headers={"content-type": "application/json"}, body=json.dumps(payload).encode()
    )


def rule(route="GET /pets", **kwargs):
    return Rule(name=kwargs.pop("name", "r"), route=route, **kwargs)


def body(result):
    return json.loads(result.body)


class TestRouting:
    def test_generated_response_uses_lowest_2xx(self, petstore):
        result = MockEngine(petstore).handle(get("/pets"))
        assert result.status == 200 and result.source == "generated"
        assert set(body(result)) >= {"items", "total"}

    def test_example_beats_generation(self, petstore):
        result = MockEngine(petstore).handle(get("/store/inventory"))
        assert result.source == "example"
        assert body(result) == {"available": 12, "pending": 3, "sold": 40}

    def test_unknown_route_lists_closest(self, petstore):
        result = MockEngine(petstore).handle(get("/pet"))
        assert result.status == 404
        assert "/pets" in body(result)["closest_routes"]

    def test_wrong_method(self, petstore):
        result = MockEngine(petstore).handle(RawRequest("PUT", "/pets"))
        assert result.status == 405 and "GET" in result.headers["allow"]

    def test_no_spec(self):
        assert MockEngine(None).handle(get("/pets")).status == 404

    def test_204_has_no_body(self, petstore):
        result = MockEngine(petstore).handle(RawRequest("DELETE", "/pets/1"))
        assert result.status == 204 and result.body == b""

    def test_repeatable_per_seed_and_path(self, petstore):
        one = MockEngine(petstore, seed=1)
        assert one.handle(get("/pets/1")).body == MockEngine(petstore, seed=1).handle(get("/pets/1")).body
        assert one.handle(get("/pets/1")).body != MockEngine(petstore, seed=2).handle(get("/pets/1")).body
        assert one.handle(get("/pets/1")).body != one.handle(get("/pets/2")).body


class TestValidation:
    @pytest.mark.parametrize(
        "request_, where",
        [
            (get("/pets", query=[("limit", "abc")]), "limit"),
            (get("/pets", query=[("limit", "0")]), "limit"),
            (get("/pets", query=[("status", "nope")]), "status"),
            (get("/pets/abc"), "id"),
            (post_json("/pets", {}), "body"),
            (post_json("/pets", {"name": ""}), "/name"),
            (RawRequest("POST", "/pets"), "body"),
            (RawRequest("POST", "/pets", headers={"content-type": "text/plain"}, body=b"x"), "body"),
            (RawRequest("POST", "/pets", headers={"content-type": "application/json"}, body=b"{bad"), "body"),
        ],
    )
    def test_rejected_with_problem_json(self, petstore, request_, where):
        result = MockEngine(petstore).handle(request_)
        assert result.status == 400 and result.source == "validation"
        assert result.headers["content-type"] == "application/problem+json"
        payload = body(result)
        assert payload["status"] == 400 and payload["errors"]
        assert where in payload["detail"]

    @pytest.mark.parametrize("raw_body", [b'"a string"', b"null", b"42", b"[]", b"true"])
    def test_json_body_of_the_wrong_type_is_rejected(self, petstore, raw_body):
        request = RawRequest("POST", "/pets", headers={"content-type": "application/json"}, body=raw_body)
        assert MockEngine(petstore).handle(request).status == 400

    @pytest.mark.parametrize("value, status", [("9223372036854775807", 200), ("9223372036854775808", 400)])
    def test_int64_bounds(self, petstore, value, status):
        assert MockEngine(petstore).handle(get(f"/pets/{value}")).status == status

    def test_valid_requests_pass(self, petstore):
        engine = MockEngine(petstore)
        assert engine.handle(get("/pets", query=[("limit", "5"), ("status", "sold")])).status == 200
        assert engine.handle(post_json("/pets", {"name": "Rex", "tag": None})).status == 201

    def test_undeclared_query_params_are_allowed(self, petstore):
        assert MockEngine(petstore).handle(get("/pets", query=[("extra", "1")])).status == 200

    def test_can_be_turned_off(self, petstore):
        result = MockEngine(petstore, validate=False).handle(get("/pets", query=[("limit", "abc")]))
        assert result.status == 200

    def test_read_only_required_fields_are_not_demanded(self):
        spec = compile_spec(
            json.dumps(
                {
                    "openapi": "3.0.3",
                    "info": {"title": "T", "version": "1"},
                    "paths": {
                        "/x": {
                            "post": {
                                "requestBody": {
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "required": ["id", "name"],
                                                "properties": {
                                                    "id": {"type": "integer", "readOnly": True},
                                                    "name": {"type": "string"},
                                                },
                                            }
                                        }
                                    }
                                },
                                "responses": {"200": {"description": "ok"}},
                            }
                        }
                    },
                }
            )
        )
        assert MockEngine(spec).handle(post_json("/x", {"name": "a"})).status == 200
        assert MockEngine(spec).handle(post_json("/x", {})).status == 400

    @pytest.mark.parametrize(
        "query, good",
        [
            ([("ids", "1"), ("ids", "2")], True),
            ([("ids", "1"), ("ids", "x")], False),
        ],
    )
    def test_exploded_array_params(self, query, good):
        spec = compile_spec(
            "openapi: 3.0.3\ninfo: {title: T, version: '1'}\npaths:\n  /x:\n    get:\n"
            "      parameters:\n        - {name: ids, in: query, schema: {type: array, items: {type: integer}}}\n"
            "      responses: {'200': {description: ok}}\n"
        )
        assert (MockEngine(spec).handle(get("/x", query=query)).status == 200) is good

    def test_hostile_pattern_in_spec_does_not_hang(self):
        spec = compile_spec(
            "openapi: 3.0.3\ninfo: {title: T, version: '1'}\npaths:\n  /x:\n    get:\n"
            "      parameters:\n        - {name: q, in: query, schema: {type: string, pattern: '^(a|a)*$'}}\n"
            "      responses: {'200': {description: ok}}\n"
        )
        started = time.perf_counter()
        MockEngine(spec).handle(get("/x", query=[("q", "a" * 64 + "!")]))
        assert time.perf_counter() - started < 1


class TestRules:
    def test_first_match_by_priority(self, petstore):
        rules = [
            ("late", rule(name="late", priority=50, then={"status": 200, "body": {"who": "late"}})),
            ("early", rule(name="early", priority=10, then={"status": 200, "body": {"who": "early"}})),
        ]
        result = MockEngine(petstore, rules).handle(get("/pets"))
        assert body(result) == {"who": "early"} and result.rule_id == "early"

    def test_ties_keep_creation_order(self, petstore):
        rules = [
            ("a", rule(then={"body": {"who": "a"}})),
            ("b", rule(then={"body": {"who": "b"}})),
        ]
        assert body(MockEngine(petstore, rules).handle(get("/pets"))) == {"who": "a"}

    def test_disabled_rule_is_skipped(self, petstore):
        rules = [("a", rule(enabled=False, then={"body": {"who": "a"}}))]
        assert MockEngine(petstore, rules).handle(get("/pets")).source == "generated"

    def test_status_only_rule_generates_from_the_spec(self, petstore):
        rules = [("a", rule("GET /pets/{id}", then={"status": 404}))]
        result = MockEngine(petstore, rules).handle(get("/pets/1"))
        assert result.status == 404 and "message" in body(result) and result.source == "rule"

    def test_status_only_rule_for_undeclared_status(self, petstore):
        rules = [("a", rule("GET /pets/{id}", then={"status": 418}))]
        result = MockEngine(petstore, rules).handle(get("/pets/1"))
        assert result.status == 418

    def test_explicit_null_body_is_not_generated(self, petstore):
        rules = [("a", rule(then={"status": 200, "body": None}))]
        assert body(MockEngine(petstore, rules).handle(get("/pets"))) is None

    def test_delay_and_headers(self, petstore):
        rules = [("a", rule(then={"body": {}, "delay_ms": 300, "headers": {"X-Who": "{{request.query.q}}"}}))]
        result = MockEngine(petstore, rules).handle(get("/pets", query=[("q", "me")]))
        assert result.delay_ms == 300 and result.headers["x-who"] == "me"

    def test_header_values_cannot_split_the_response(self, petstore):
        rules = [("a", rule(then={"body": {}, "headers": {"x-who": "{{request.query.q}}"}}))]
        result = MockEngine(petstore, rules).handle(get("/pets", query=[("q", "a\r\nSet-Cookie: evil=1")]))
        assert "\r" not in result.headers["x-who"] and "\n" not in result.headers["x-who"]

    def test_all_example_rules_run_against_petstore(self, petstore):
        rules = [
            (p.stem, Rule.model_validate(json.loads(p.read_text())))
            for p in sorted((ROOT / "examples" / "rules" / "petstore").glob("*.json"))
        ]
        engine = MockEngine(petstore, rules)
        assert body(engine.handle(get("/pets", query=[("status", "empty")]))) == {"items": [], "total": 0}
        assert engine.handle(get("/pets/999")).status == 404
        assert body(engine.handle(get("/pets/42")))["id"] == 42
        assert engine.handle(get("/pets", headers={"x-user-tier": "free"})).status == 402
        assert engine.handle(post_json("/pets", {"name": "Rex"})).status == 400
        assert engine.handle(post_json("/pets", {"name": "Tom", "price": 5000})).status == 400
        assert body(engine.handle(post_json("/pets", {"name": "Tom", "tag": "x"})))["tag"] == "X"
        created = engine.handle(post_json("/pets", {"name": "Tom", "price": 5}))
        assert created.status == 201 and body(created)["price"] == 5 and "location" in created.headers
        assert engine.handle(RawRequest("DELETE", "/pets/1", cookies={"role": "admin"})).rule_name


class TestChaos:
    def engine(self, petstore, config, key=None, **kwargs):
        return MockEngine(petstore, chaos={key: config}, chaos_rng=random.Random(1), **kwargs)

    def test_fixed_latency(self, petstore):
        result = self.engine(petstore, ChaosConfig(latency_min_ms=250)).handle(get("/pets"))
        assert result.delay_ms == 250 and result.status == 200

    def test_latency_range(self, petstore):
        engine = self.engine(petstore, ChaosConfig(latency_min_ms=100, latency_max_ms=200))
        delays = {engine.handle(get("/pets")).delay_ms for _ in range(30)}
        assert len(delays) > 1 and all(100 <= d <= 200 for d in delays)

    def test_rule_delay_adds_and_total_is_capped(self, petstore):
        rules = [("a", rule(then={"body": {}, "delay_ms": 60_000}))]
        engine = MockEngine(petstore, rules, {None: ChaosConfig(latency_min_ms=60_000)})
        assert engine.handle(get("/pets")).delay_ms == 60_000

    def test_error_rate_extremes(self, petstore):
        never = self.engine(petstore, ChaosConfig(error_rate=0.0))
        always = self.engine(petstore, ChaosConfig(error_rate=1.0))
        assert all(never.handle(get("/pets")).status == 200 for _ in range(20))
        assert all(always.handle(get("/pets")).status == 500 for _ in range(20))

    def test_error_rate_is_roughly_honoured(self, petstore):
        engine = self.engine(petstore, ChaosConfig(error_rate=0.3))
        failures = sum(engine.handle(get("/pets")).status == 500 for _ in range(1000))
        assert 230 < failures < 370

    def test_forced_status_uses_the_specs_response_when_declared(self, petstore):
        result = self.engine(petstore, ChaosConfig(forced_status=404)).handle(get("/pets/1"))
        assert result.status == 404 and "message" in body(result)
        assert result.source == "chaos"

    def test_forced_status_beats_a_rule(self, petstore):
        rules = [("a", rule(then={"status": 200, "body": {}}))]
        engine = MockEngine(petstore, rules, {None: ChaosConfig(forced_status=503)})
        assert engine.handle(get("/pets")).status == 503

    def test_offline_drops(self, petstore):
        assert self.engine(petstore, ChaosConfig(offline=True)).handle(get("/pets")).drop_connection

    def test_route_setting_overrides_global(self, petstore):
        engine = MockEngine(
            petstore,
            chaos={None: ChaosConfig(forced_status=500), "GET /pets": ChaosConfig()},
        )
        assert engine.handle(get("/pets")).status == 200
        assert engine.handle(get("/pets/1")).status == 500

    def test_chaos_does_not_poison_the_response_cache(self, petstore):
        forced = MockEngine(petstore, chaos={None: ChaosConfig(forced_status=500)})
        assert forced.handle(get("/pets")).status == 500
        forced.chaos = {}
        assert forced.handle(get("/pets")).status == 200


def test_oversized_generated_response_is_refused():
    spec = compile_spec(
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {"title": "T", "version": "1"},
                "paths": {
                    "/x": {
                        "get": {
                            "responses": {
                                "200": {
                                    "description": "ok",
                                    "content": {
                                        "application/json": {"schema": {"type": "string", "minLength": 2_000_000}}
                                    },
                                }
                            }
                        }
                    }
                },
            }
        )
    )
    engine = MockEngine(spec)
    assert engine.handle(get("/x")).status == 500
    assert engine.handle(get("/x")).status == 500  # also when served from the cache
