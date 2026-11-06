"""Rule model and evaluation. Rules are plain JSON so the UI can build them without code."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

import regex
from jsonpath_ng.exceptions import JsonPathLexerError, JsonPathParserError
from jsonpath_ng.ext import parse as parse_jsonpath
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .limits import MAX_DELAY_MS, MAX_RESPONSE_BYTES, REGEX_TIMEOUT_SECONDS
from .schema import SchemaContext
from .templating import TemplateError, check_templates

Source = Literal["path", "query", "header", "cookie", "body"]
Operator = Literal[
    "eq", "neq", "in", "contains", "regex", "gt", "lt", "exists", "matches_schema"
]  # fmt: skip


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Source
    field: str = Field(
        min_length=1,
        description="Parameter, header or cookie name; a JSONPath such as $.items[0].sku for body.",
    )
    op: Operator
    value: Any = None

    @model_validator(mode="after")
    def _value_fits_operator(self) -> Condition:
        if self.op == "in" and not isinstance(self.value, list):
            raise ValueError("'in' needs a list value")
        if self.op == "regex":
            if not isinstance(self.value, str):
                raise ValueError("'regex' needs a string pattern")
            try:
                regex.compile(self.value)
            except regex.error as exc:
                raise ValueError(f"Invalid regex: {exc}") from exc
        if self.op in ("gt", "lt"):
            try:
                float(self.value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"'{self.op}' needs a numeric value") from exc
        if self.op == "matches_schema":
            if not isinstance(self.value, dict):
                raise ValueError("'matches_schema' needs a JSON Schema object")
            try:
                Draft202012Validator.check_schema(self.value)
            except SchemaError as exc:
                raise ValueError(f"Invalid JSON Schema: {exc.message}") from exc
        if self.source == "body":
            try:
                parse_jsonpath(_as_jsonpath(self.field))
            except (JsonPathParserError, JsonPathLexerError, Exception) as exc:
                raise ValueError(f"Invalid JSONPath '{self.field}': {exc}") from exc
        return self


class When(BaseModel):
    model_config = ConfigDict(extra="forbid")

    all: list[Condition] | None = None
    any: list[Condition] | None = None

    @model_validator(mode="after")
    def _one_group(self) -> When:
        if self.all is not None and self.any is not None:
            raise ValueError("Use either 'all' or 'any', not both")
        return self


class Then(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Annotated[int, Field(ge=100, le=599)] = 200
    body: Any = Field(
        default=None,
        description="JSON value or template string. Leave out to generate from the spec's schema.",
    )
    headers: dict[str, str] = Field(default_factory=dict)
    delay_ms: Annotated[int, Field(ge=0, le=MAX_DELAY_MS)] = 0

    @model_validator(mode="after")
    def _templates_compile(self) -> Then:
        if len(repr(self.body)) > MAX_RESPONSE_BYTES:
            raise ValueError("Response body is larger than the 1 MB limit")
        try:
            check_templates(self.body)
            check_templates(self.headers)
        except TemplateError as exc:
            raise ValueError(str(exc)) from exc
        return self

    @property
    def has_body(self) -> bool:
        return "body" in self.model_fields_set


class Rule(BaseModel):
    """One rule. Lower priority numbers are evaluated first; ties keep creation order."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    route: str = Field(description="Route key such as 'GET /users/{id}'.")
    priority: int = 100
    enabled: bool = True
    when: When = Field(default_factory=When)
    then: Then = Field(default_factory=Then)


def _as_jsonpath(field_name: str) -> str:
    return field_name if field_name.startswith("$") else f"$.{field_name}"


@dataclass
class RequestView:
    """The request as rules and templates see it: parameters are already coerced to types."""

    method: str
    url: str
    path: dict[str, Any]
    query: dict[str, Any]
    headers: dict[str, str]
    cookies: dict[str, str]
    body: Any = None
    notes: list[str] = field(default_factory=list)

    def template_data(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "url": self.url,
            "path": self.path,
            "query": self.query,
            "headers": self.headers,
            "cookies": self.cookies,
            "body": self.body,
        }


_MISSING = object()


def _as_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return str(value)


def _loose_equal(left: Any, right: Any) -> bool:
    # Query strings and JSON disagree on types, and "42" should match 42 in a no-code rule.
    return left == right or _as_text(left) == _as_text(right)


class CompiledCondition:
    def __init__(self, condition: Condition, context: SchemaContext | None):
        self.condition = condition
        self.jsonpath = (
            parse_jsonpath(_as_jsonpath(condition.field)) if condition.source == "body" else None
        )
        self.schema_validator = None
        if condition.op == "matches_schema":
            self.schema_validator = (
                context.validator(condition.value)
                if context
                else Draft202012Validator(condition.value)
            )

    def _read(self, request: RequestView) -> Any:
        source = self.condition.source
        name = self.condition.field
        if source == "body":
            if request.body is None:
                return _MISSING
            found = self.jsonpath.find(request.body)
            return found[0].value if found else _MISSING
        if source == "header":
            return request.headers.get(name.lower(), _MISSING)
        bag = {"path": request.path, "query": request.query, "cookie": request.cookies}[source]
        return bag.get(name, _MISSING)

    def matches(self, request: RequestView) -> bool:
        actual = self._read(request)
        op, expected = self.condition.op, self.condition.value
        if op == "exists":
            present = actual is not _MISSING
            return present if expected is None or expected is True else not present
        if op == "neq":
            return actual is _MISSING or not _loose_equal(actual, expected)
        if actual is _MISSING:
            return False
        if op == "eq":
            return _loose_equal(actual, expected)
        if op == "in":
            return any(_loose_equal(actual, item) for item in expected)
        if op == "contains":
            if isinstance(actual, (list, tuple)):
                return any(_loose_equal(item, expected) for item in actual)
            if isinstance(actual, dict):
                return str(expected) in actual
            return _as_text(expected) in _as_text(actual)
        if op == "regex":
            try:
                return bool(regex.search(expected, _as_text(actual), timeout=REGEX_TIMEOUT_SECONDS))
            except TimeoutError:
                request.notes.append(f"Regex on {self.condition.field} timed out; treated as no match.")
                return False
        if op in ("gt", "lt"):
            try:
                left, right = float(actual), float(expected)
            except (TypeError, ValueError):
                return False
            return left > right if op == "gt" else left < right
        if op == "matches_schema":
            try:
                return next(self.schema_validator.iter_errors(actual), None) is None
            except Exception:  # noqa: BLE001 - a bad schema cannot match
                return False
        return False  # pragma: no cover


class CompiledRule:
    def __init__(self, rule_id: str, rule: Rule, context: SchemaContext | None = None):
        self.id = rule_id
        self.rule = rule
        self.mode = "any" if rule.when.any is not None else "all"
        conditions = rule.when.any if rule.when.any is not None else (rule.when.all or [])
        self.conditions = [CompiledCondition(c, context) for c in conditions]

    def matches(self, request: RequestView) -> bool:
        if not self.conditions:
            return True
        check = any if self.mode == "any" else all
        return check(c.matches(request) for c in self.conditions)


def rule_json_schema() -> dict[str, Any]:
    return Rule.model_json_schema()
