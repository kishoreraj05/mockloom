"""Sandboxed response templates: {{request.path.id}}, {{faker.email}}, {{now}}.

The sandbox alone is not enough. `{{ 9**9**9 }}` and nested loops pass Jinja's sandbox and hang
the event loop that serves every mock. So templates are limited by construction to an AST
allowlist with no loops, arithmetic, calls or literals that grow. Render cost is then bounded by
the size of the template and the request, and no timer is needed.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from faker import Faker
from jinja2 import ChainableUndefined, TemplateSyntaxError, nodes
from jinja2.sandbox import SandboxedEnvironment

ALLOWED_NAMES = {"request", "faker", "now"}
ALLOWED_FILTERS = {
    "abs", "capitalize", "default", "d", "first", "float", "int", "join", "last", "length",
    "lower", "round", "string", "title", "tojson", "trim", "upper",
}  # fmt: skip
ALLOWED_TESTS = {"defined", "undefined", "none", "number", "string", "boolean", "true", "false"}
_ALLOWED_NODES = (
    nodes.Template, nodes.Output, nodes.TemplateData, nodes.Name, nodes.Getattr, nodes.Getitem,
    nodes.Const, nodes.Filter, nodes.Test, nodes.Keyword, nodes.CondExpr, nodes.Compare,
    nodes.Operand, nodes.And, nodes.Or, nodes.Not,
)  # fmt: skip

FAKER_PROVIDERS = {
    "address", "boolean", "bs", "catch_phrase", "city", "color_name", "company", "country",
    "country_code", "currency_code", "date", "date_time", "domain_name", "email", "file_name",
    "first_name", "hex_color", "image_url", "ipv4", "ipv6", "job", "language_code", "last_name",
    "locale", "md5", "name", "paragraph", "password", "phone_number", "postcode", "sentence",
    "sha1", "sha256", "slug", "state", "street_address", "text", "url", "user_agent",
    "user_name", "uuid4", "word",
}  # fmt: skip


class TemplateError(ValueError):
    pass


class FakerProxy:
    """Exposes `faker.email` as a value. Only allowlisted providers are reachable."""

    def __init__(self, faker: Faker):
        self._faker = faker

    def __getattr__(self, name: str) -> Any:
        if name in FAKER_PROVIDERS:
            value = getattr(self._faker, name)()
            return value.isoformat() if isinstance(value, (dt.date, dt.datetime)) else value
        raise AttributeError(name)


class _Environment(SandboxedEnvironment):
    def getattr(self, obj: Any, attribute: str) -> Any:
        # Dot access on a mapping means a key, so {{request.query.items}} reads ?items=.
        if isinstance(obj, Mapping):
            return obj[attribute] if attribute in obj else self.undefined(name=attribute)
        return super().getattr(obj, attribute)


_env = _Environment(undefined=ChainableUndefined, autoescape=False)
_WHOLE_EXPRESSION = re.compile(r"^\s*\{\{(.*)\}\}\s*$", re.DOTALL)


def _check_ast(ast: nodes.Node) -> None:
    for node in [ast, *ast.find_all(nodes.Node)]:
        if not isinstance(node, _ALLOWED_NODES):
            raise TemplateError(
                f"{type(node).__name__} is not allowed in templates; "
                "use {{ value }} expressions, filters and inline if/else."
            )
        if isinstance(node, nodes.Name) and node.name not in ALLOWED_NAMES:
            raise TemplateError(
                f"Unknown name '{node.name}'; use one of {', '.join(sorted(ALLOWED_NAMES))}."
            )
        if isinstance(node, nodes.Getattr) and node.attr.startswith("_"):
            raise TemplateError("Attributes starting with '_' are not accessible.")
        if isinstance(node, nodes.Filter) and node.name not in ALLOWED_FILTERS:
            raise TemplateError(f"Filter '{node.name}' is not allowed.")
        if isinstance(node, nodes.Test) and node.name not in ALLOWED_TESTS:
            raise TemplateError(f"Test '{node.name}' is not allowed.")
        if (
            isinstance(node, nodes.Getattr)
            and isinstance(node.node, nodes.Name)
            and node.node.name == "faker"
            and node.attr not in FAKER_PROVIDERS
        ):
            raise TemplateError(f"Unknown faker provider '{node.attr}'.")


@lru_cache(maxsize=2048)
def _compile(source: str) -> tuple[Any, Any]:
    """Returns (template, native_expression); the expression is set for a lone {{ expr }}."""
    try:
        ast = _env.parse(source)
    except TemplateSyntaxError as exc:
        raise TemplateError(f"Template syntax error: {exc.message}") from exc
    _check_ast(ast)
    native = None
    whole = _WHOLE_EXPRESSION.match(source)
    if (
        whole
        and len(ast.body) == 1
        and isinstance(ast.body[0], nodes.Output)
        and len(ast.body[0].nodes) == 1
        and not isinstance(ast.body[0].nodes[0], nodes.TemplateData)
    ):
        native = _env.compile_expression(whole.group(1), undefined_to_none=True)
    return _env.from_string(source), native


def _is_template(value: str) -> bool:
    return "{{" in value or "{%" in value or "{#" in value


def check_templates(value: Any) -> None:
    """Raise TemplateError for the first bad template anywhere in a JSON value."""
    if isinstance(value, str):
        if _is_template(value):
            _compile(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            check_templates(key)
            check_templates(item)
    elif isinstance(value, list):
        for item in value:
            check_templates(item)


def render(value: Any, context: dict[str, Any]) -> Any:
    """Render every template in a JSON value. A lone {{ expr }} keeps its native type."""
    if isinstance(value, str):
        if not _is_template(value):
            return value
        template, native = _compile(value)
        if native is not None:
            return native(**context)
        return template.render(**context)
    if isinstance(value, dict):
        return {str(render(k, context)): render(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, context) for v in value]
    return value


def template_context(request: dict[str, Any], faker: Faker) -> dict[str, Any]:
    now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    return {
        "request": request,
        "faker": FakerProxy(faker),
        "now": now.isoformat().replace("+00:00", "Z"),
    }
