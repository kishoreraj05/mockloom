"""The request pipeline: match, validate, apply rules, generate, then chaos.

It never sleeps and never touches I/O. It returns a MockResult saying what to send and how long
to wait, so the web layer stays thin and the engine stays usable on its own.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from faker import Faker
from jinja2 import TemplateError as JinjaError

from .compiler import CompiledResponse, CompiledRoute, CompiledSpec, MediaType
from .generator import Generator
from .limits import MAX_DELAY_MS, MAX_RESPONSE_BYTES
from .request import RawRequest, ValidationIssue, is_json_type, media_matches, read_request
from .rules import CompiledRule, RequestView, Rule
from .templating import TemplateError, render, template_context

_rule_faker = Faker()
_PROBLEM = "application/problem+json"
_NO_BODY = {204, 205, 304}


@dataclass
class ChaosConfig:
    latency_min_ms: int = 0
    latency_max_ms: int = 0
    error_rate: float = 0.0  # 0..1
    forced_status: int | None = None
    offline: bool = False


@dataclass
class MockResult:
    status: int
    headers: dict[str, str]
    body: bytes
    route_key: str | None = None
    rule_id: str | None = None
    rule_name: str | None = None
    delay_ms: int = 0
    drop_connection: bool = False
    chaos: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    source: str = "generated"  # generated | example | rule | validation | chaos | error


def _problem(status: int, title: str, detail: str, **extra: Any) -> tuple[dict[str, str], bytes]:
    payload = {"type": "about:blank", "title": title, "status": status, "detail": detail, **extra}
    return {"content-type": _PROBLEM}, json.dumps(payload).encode()


def _encode(value: Any, content_type: str) -> bytes:
    if value is None and not is_json_type(content_type):
        return b""
    if isinstance(value, str) and not is_json_type(content_type):
        return value.encode()
    return json.dumps(value, ensure_ascii=False, default=str).encode()


def _seed_material(*parts: Any) -> int:
    digest = hashlib.sha256(":".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _select_media(response: CompiledResponse, accept: str) -> MediaType | None:
    if not response.content:
        return None
    wanted = [part.split(";")[0].strip() for part in accept.split(",") if part.strip()]
    for want in wanted:
        if want in ("*/*", ""):
            continue
        for media in response.content:
            if media_matches(want, media.content_type) or media_matches(media.content_type, want):
                return media
    for media in response.content:
        if is_json_type(media.content_type):
            return media
    return response.content[0]


def _status_int(status: str, fallback: int = 200) -> int:
    if status.isdigit():
        return int(status)
    if len(status) == 3 and status[0].isdigit():  # 2XX, 4xx
        return int(status[0]) * 100
    return fallback


class MockEngine:
    """Everything needed to serve one workspace. Rebuilt whenever its configuration changes."""

    def __init__(
        self,
        spec: CompiledSpec | None,
        rules: Iterable[tuple[str, Rule]] = (),
        chaos: dict[str | None, ChaosConfig] | None = None,
        seed: int = 0,
        validate: bool = True,
        chaos_rng: random.Random | None = None,
    ):
        self.spec = spec
        self.seed = seed
        self.validate = validate
        self.chaos = chaos or {}
        self.chaos_rng = chaos_rng or random.Random()
        self.rules: dict[str, list[CompiledRule]] = {}
        context = spec.context if spec else None
        ordered = sorted(enumerate(rules), key=lambda pair: (pair[1][1].priority, pair[0]))
        for _, (rule_id, rule) in ordered:
            if rule.enabled:
                self.rules.setdefault(rule.route, []).append(CompiledRule(rule_id, rule, context))
        # Generated output is a pure function of its key, so it is safe to reuse.
        self._generated: OrderedDict[tuple, tuple[int, dict[str, str], bytes, str]] = OrderedDict()

    def handle(self, raw: RawRequest) -> MockResult:
        result = self._respond(raw)
        return self._apply_chaos(raw, result)

    def _respond(self, raw: RawRequest) -> MockResult:
        if self.spec is None:
            headers, body = _problem(
                404, "No spec", "This workspace has no spec yet. Upload one to start mocking."
            )
            return MockResult(404, headers, body, source="error")

        match = self.spec.match(raw.method, raw.path)
        if match.route is None:
            return self._no_route(raw, match.allowed_methods)

        route = match.route
        view, issues = read_request(raw, route, match.path_params, self.spec.context)
        if issues and self.validate:
            return self._rejected(route, issues)

        for rule in self.rules.get(route.key, ()):
            if rule.matches(view):
                result = self._from_rule(rule, route, raw, view)
                result.notes.extend(view.notes)
                return result

        result = self._generate(route, raw, None)
        result.notes.extend(view.notes)
        return result

    def _no_route(self, raw: RawRequest, allowed: list[str]) -> MockResult:
        assert self.spec is not None
        if allowed:
            headers, body = _problem(
                405,
                "Method not allowed",
                f"{raw.path} does not support {raw.method}.",
                allowed=allowed,
            )
            headers["allow"] = ", ".join(allowed)
            return MockResult(405, headers, body, source="error")
        closest = self.spec.closest_routes(raw.path)
        headers, body = _problem(
            404,
            "No matching route",
            f"The spec has no route for {raw.method} {raw.path}.",
            closest_routes=closest,
        )
        return MockResult(404, headers, body, source="error")

    def _rejected(self, route: CompiledRoute, issues: list[ValidationIssue]) -> MockResult:
        first = issues[0]
        where = f"{first.location} '{first.name}'" if first.name else first.location
        headers, body = _problem(
            400,
            "Request does not match the spec",
            f"{where}: {first.message}",
            errors=[{"in": i.location, "name": i.name, "message": i.message} for i in issues],
        )
        return MockResult(400, headers, body, route_key=route.key, source="validation")

    def _from_rule(
        self, compiled: CompiledRule, route: CompiledRoute, raw: RawRequest, view: RequestView
    ) -> MockResult:
        then = compiled.rule.then
        _rule_faker.seed_instance(_seed_material(self.seed, compiled.id, raw.path))
        context = template_context(view.template_data(), _rule_faker)
        try:
            if then.has_body:
                value = render(then.body, context)
                content_type = then.headers.get("content-type") or then.headers.get("Content-Type")
                if not content_type:
                    content_type = "text/plain" if isinstance(value, str) else "application/json"
                payload = b"" if then.status in _NO_BODY else _encode(value, content_type)
                headers = {} if then.status in _NO_BODY else {"content-type": content_type}
                result = MockResult(then.status, headers, payload, route_key=route.key)
            else:
                result = self._generate(route, raw, str(then.status))
                result.status = then.status
            for name, template in then.headers.items():
                rendered = str(render(template, context))
                # Values can come from the request, so they must not be able to split the response.
                result.headers[name.lower()] = rendered.replace("\r", " ").replace("\n", " ")
        except (TemplateError, JinjaError, ValueError, TypeError) as exc:
            headers, body = _problem(500, "Rule template failed", f"{compiled.rule.name}: {exc}")
            return MockResult(
                500, headers, body, route.key, compiled.id, compiled.rule.name, source="error"
            )
        result.rule_id = compiled.id
        result.rule_name = compiled.rule.name
        result.delay_ms = then.delay_ms
        result.source = "rule"
        return self._enforce_size(result)

    def _generate(
        self, route: CompiledRoute, raw: RawRequest, status: str | None
    ) -> MockResult:
        """The default response: the declared example if any, otherwise fake data."""
        accept = raw.headers.get("accept", "")
        key = (route.key, raw.path, status, accept)
        cached = self._generated.get(key)
        if cached is not None:
            self._generated.move_to_end(key)
            code, headers, body, source = cached
            return self._enforce_size(
                MockResult(code, dict(headers), body, route_key=route.key, source=source)
            )

        code, headers, body, source = self._build(route, raw.path, status, accept)
        self._generated[key] = (code, headers, body, source)
        if len(self._generated) > 512:
            self._generated.popitem(last=False)
        return self._enforce_size(
            MockResult(code, dict(headers), body, route_key=route.key, source=source)
        )

    def _build(
        self, route: CompiledRoute, path: str, wanted: str | None, accept: str
    ) -> tuple[int, dict[str, str], bytes, str]:
        status = wanted if wanted is not None else route.default_status()
        if wanted is not None and wanted not in route.responses:
            # Fall back to a wildcard (4XX) or `default` if the exact code is not declared.
            wildcard = f"{wanted[0]}XX"
            status = next(
                (s for s in (wildcard, wildcard.lower(), "default") if s in route.responses), None
            )
            if status is None:
                code = _status_int(wanted)
                if code in _NO_BODY:
                    return code, {}, b"", "generated"
                headers, body = _problem(code, f"Status {code}", "Injected by MockForge.")
                return code, headers, body, "generated"
        if status is None:
            return 200, {}, b"", "generated"

        code = int(wanted) if wanted is not None else _status_int(status)
        response = route.responses[status]
        headers = self._response_headers(response, route, path, status)
        media = _select_media(response, accept)
        if media is None or code in _NO_BODY:
            return code, headers, b"", "generated"
        headers["content-type"] = media.content_type
        if media.has_example:
            return code, headers, _encode(media.example, media.content_type), "example"
        assert self.spec is not None
        rng = random.Random(_seed_material(self.seed, route.key, path, status))
        value = Generator(self.spec.context, rng).generate(media.schema)
        return code, headers, _encode(value, media.content_type), "generated"

    def _response_headers(
        self, response: CompiledResponse, route: CompiledRoute, path: str, status: str
    ) -> dict[str, str]:
        assert self.spec is not None
        headers: dict[str, str] = {}
        if not response.headers:
            return headers
        rng = random.Random(_seed_material(self.seed, route.key, path, status, "headers"))
        generator = Generator(self.spec.context, rng)
        for name, raw in response.headers.items():
            if name.lower() == "content-type":
                continue
            header = self.spec.context.resolve(raw)
            schema = header.get("schema")
            value = header["example"] if "example" in header else generator.generate(schema, name)
            if value is not None:
                text = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
                # Generated text must not be able to split the HTTP response.
                headers[name.lower()] = text.replace("\r", " ").replace("\n", " ")[:1024]
        return headers

    def _enforce_size(self, result: MockResult) -> MockResult:
        if len(result.body) <= MAX_RESPONSE_BYTES:
            return result
        headers, body = _problem(
            500, "Response too large", "The response body is over the 1 MB limit."
        )
        result.status, result.headers, result.body, result.source = 500, headers, body, "error"
        return result

    def _apply_chaos(self, raw: RawRequest, result: MockResult) -> MockResult:
        config = None
        if result.route_key is not None:
            config = self.chaos.get(result.route_key)
        if config is None:
            config = self.chaos.get(None)
        if config is None:
            return result

        if config.latency_max_ms > 0:
            low = min(config.latency_min_ms, config.latency_max_ms)
            delay = self.chaos_rng.randint(low, config.latency_max_ms)
            result.delay_ms = result.delay_ms + delay
            result.chaos.append(f"latency {delay}ms")
        elif config.latency_min_ms > 0:
            result.delay_ms = result.delay_ms + config.latency_min_ms
            result.chaos.append(f"latency {config.latency_min_ms}ms")
        result.delay_ms = min(result.delay_ms, MAX_DELAY_MS)

        if config.offline:
            result.drop_connection = True
            result.chaos.append("offline")
            return result
        if config.forced_status is not None:
            result.chaos.append(f"forced {config.forced_status}")
            return self._replace_status(raw, result, config.forced_status)
        if config.error_rate > 0 and self.chaos_rng.random() < config.error_rate:
            result.chaos.append("random error")
            return self._replace_status(raw, result, self._error_status(result.route_key))
        return result

    def _error_status(self, route_key: str | None) -> int:
        if self.spec is not None and route_key in self.spec.routes:
            for status in sorted(self.spec.routes[route_key].responses):
                if status.isdigit() and status.startswith("5"):
                    return int(status)
        return 500

    def _replace_status(self, raw: RawRequest, result: MockResult, status: int) -> MockResult:
        route = self.spec.routes.get(result.route_key) if self.spec and result.route_key else None
        if route is not None:
            code, headers, body, _ = self._build(route, raw.path, str(status), raw.headers.get("accept", ""))
        else:
            headers, body = _problem(status, f"Status {status}", "Injected by MockForge.")
            code = status
        result.status, result.headers, result.body = code, headers, body
        result.source = "chaos"
        return self._enforce_size(result)


def sample_body(spec: CompiledSpec, schema: Any, seed: int = 0, name: str | None = None) -> Any:
    """A repeatable example value for a schema. Used to pre-fill the editors in the UI."""
    rng = random.Random(_seed_material(seed, "sample", name))
    return Generator(spec.context, rng).generate(schema, name)
