"""Turn a raw HTTP request into typed values, and check it against the operation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl

from .compiler import CompiledParam, CompiledRoute, MediaType
from .limits import MAX_VALIDATION_ERRORS
from .rules import RequestView
from .schema import SchemaContext, collect_errors

_INTEGER = re.compile(r"-?[0-9]+")
_NUMBER = re.compile(r"-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?")

# OpenAPI: header parameters with these names are ignored, since HTTP itself governs them.
_IGNORED_HEADERS = {"accept", "content-type", "authorization"}


@dataclass
class RawRequest:
    method: str
    path: str
    query: list[tuple[str, str]] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)  # keys lower-cased
    cookies: dict[str, str] = field(default_factory=dict)
    body: bytes = b""


@dataclass
class ValidationIssue:
    location: str
    name: str
    message: str


def is_json_type(content_type: str) -> bool:
    base = content_type.split(";")[0].strip().lower()
    return base == "application/json" or base.endswith("+json")


def media_matches(declared: str, actual: str) -> bool:
    declared = declared.split(";")[0].strip().lower()
    actual = actual.split(";")[0].strip().lower()
    if declared in ("*/*", actual):
        return True
    if declared.endswith("/*"):
        return actual.startswith(declared[:-1])
    return False


def _coerce_scalar(value: str, types: set[str]) -> Any:
    if "string" in types or not types:
        return value
    # Not int() and float(): they also accept " 42", "42\\n", "1_000", "nan" and "inf".
    if "integer" in types and _INTEGER.fullmatch(value):
        return int(value)
    if "number" in types and _NUMBER.fullmatch(value):
        return float(value)
    if "boolean" in types and value.lower() in ("true", "false"):
        return value.lower() == "true"
    if "null" in types and value in ("", "null"):
        return None
    return value


def coerce(value: Any, schema: Any, context: SchemaContext) -> Any:
    """Query strings are all text; apply the types the schema asks for."""
    if schema is None:
        return value
    node = context.resolve(schema)
    if isinstance(value, list):
        items = node.get("items")
        return [coerce(v, items, context) for v in value]
    if isinstance(value, dict):
        properties = node.get("properties") or {}
        return {k: coerce(v, properties.get(k), context) for k, v in value.items()}
    if isinstance(value, str):
        return _coerce_scalar(value, context.type_set(node))
    return value


_DELIMITERS = {"spaceDelimited": " ", "pipeDelimited": "|"}


def _read_query_param(
    param: CompiledParam, pairs: list[tuple[str, str]], types: set[str]
) -> tuple[bool, Any]:
    if param.style == "deepObject":
        prefix = param.name + "["
        found = {k[len(prefix) : -1]: v for k, v in pairs if k.startswith(prefix) and k.endswith("]")}
        return bool(found), found
    values = [v for k, v in pairs if k == param.name]
    if not values:
        return False, None
    if "array" in types:
        if param.explode:
            return True, values
        return True, values[-1].split(_DELIMITERS.get(param.style, ","))
    return True, values[-1]


def _select_body_media(route: CompiledRoute, content_type: str) -> MediaType | None:
    matching = [m for m in route.body_content if media_matches(m.content_type, content_type)]
    # An exact declaration beats a wildcard one.
    matching.sort(key=lambda m: "*" in m.content_type)
    return matching[0] if matching else None


def _parse_body(raw: RawRequest) -> tuple[Any, str | None]:
    """(parsed value, parse error). Unknown content types come back as text."""
    if not raw.body:
        return None, None
    content_type = raw.headers.get("content-type", "")
    if is_json_type(content_type):
        try:
            return json.loads(raw.body), None
        except (ValueError, RecursionError) as exc:
            return None, f"Body is not valid JSON: {exc}"
    if content_type.split(";")[0].strip().lower() == "application/x-www-form-urlencoded":
        grouped: dict[str, Any] = {}
        for key, value in parse_qsl(raw.body.decode("utf-8", "replace"), keep_blank_values=True):
            if key in grouped:
                existing = grouped[key]
                grouped[key] = [*existing, value] if isinstance(existing, list) else [existing, value]
            else:
                grouped[key] = value
        return grouped, None
    if content_type.startswith("multipart/"):
        return None, None
    return raw.body.decode("utf-8", "replace"), None


def read_request(
    raw: RawRequest, route: CompiledRoute, path_params: dict[str, str], context: SchemaContext
) -> tuple[RequestView, list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    query: dict[str, Any] = {}
    for key, value in raw.query:  # Undeclared parameters are legal and visible to rules.
        if key in query:
            existing = query[key]
            query[key] = [*existing, value] if isinstance(existing, list) else [existing, value]
        else:
            query[key] = value

    view = RequestView(
        method=raw.method,
        url=raw.path,
        path=dict(path_params),
        query=query,
        headers=dict(raw.headers),
        cookies=dict(raw.cookies),
    )

    for param in route.params:
        if param.location == "header" and param.name.lower() in _IGNORED_HEADERS:
            continue
        types = context.type_set(param.schema) if param.schema is not None else set()
        store: dict[str, Any]
        if param.location == "query":
            present, value = _read_query_param(param, raw.query, types)
            store = view.query
        elif param.location == "path":
            present = param.name in path_params
            value = path_params.get(param.name)
            if present and "array" in types:
                value = str(value).split(",")
            store = view.path
        elif param.location == "header":
            present = param.name.lower() in raw.headers
            value = raw.headers.get(param.name.lower())
            if present and "array" in types:
                value = [v.strip() for v in str(value).split(",")]
            store = view.headers
        else:
            present = param.name in raw.cookies
            value = raw.cookies.get(param.name)
            store = view.cookies

        if not present:
            # Exploded object parameters spread across the query, so they cannot be "missing".
            spread = "object" in types and param.location == "query" and param.style == "form"
            if param.required and not spread:
                issues.append(
                    ValidationIssue(param.location, param.name, "Required parameter is missing.")
                )
            continue

        value = coerce(value, param.schema, context)
        key = param.name.lower() if param.location == "header" else param.name
        store[key] = value
        if param.validator is not None:
            for _, message in collect_errors(param.validator, value, 3):
                issues.append(ValidationIssue(param.location, param.name, message))

    parsed, parse_error = _parse_body(raw)
    view.body = parsed
    content_type = raw.headers.get("content-type", "")
    if route.body_content or route.body_required:
        if not raw.body:
            if route.body_required:
                issues.append(ValidationIssue("body", "", "Request body is required."))
        else:
            media = _select_body_media(route, content_type)
            if media is None:
                accepted = ", ".join(m.content_type for m in route.body_content)
                issues.append(
                    ValidationIssue(
                        "body", "", f"Content-Type '{content_type or 'none'}' is not accepted; use {accepted}."
                    )
                )
            elif parse_error:
                issues.append(ValidationIssue("body", "", parse_error))
            elif media.validator is not None and (is_json_type(content_type) or isinstance(parsed, dict)):
                candidate = parsed
                if not is_json_type(content_type):  # Form fields are all text until coerced.
                    candidate = coerce(parsed, media.schema, context)
                    view.body = candidate
                for pointer, message in collect_errors(
                    media.validator, candidate, MAX_VALIDATION_ERRORS
                ):
                    issues.append(ValidationIssue("body", pointer, message))
    return view, issues[:MAX_VALIDATION_ERRORS]
