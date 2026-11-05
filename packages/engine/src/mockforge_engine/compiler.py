"""Compile an OpenAPI document into a route table."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from openapi_spec_validator import OpenAPIV30SpecValidator, OpenAPIV31SpecValidator

from .limits import MAX_SPEC_ISSUES
from .loader import SpecError, SpecIssue, line_for_path, parse_document
from .schema import SchemaContext, iter_refs, lookup_pointer, normalize_30

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
_PARAM = re.compile(r"\{([^{}]+)\}")


@dataclass
class CompiledParam:
    name: str
    location: str
    required: bool
    schema: Any
    style: str
    explode: bool
    validator: Any = None


@dataclass
class MediaType:
    content_type: str
    schema: Any
    example: Any = None
    has_example: bool = False
    validator: Any = None


@dataclass
class CompiledResponse:
    status: str
    description: str
    content: list[MediaType]
    headers: dict[str, Any]


@dataclass
class CompiledRoute:
    method: str
    template: str
    summary: str
    description: str
    tags: list[str]
    operation_id: str | None
    params: list[CompiledParam]
    body_required: bool
    body_content: list[MediaType]
    responses: dict[str, CompiledResponse]

    @property
    def key(self) -> str:
        return f"{self.method} {self.template}"

    def default_status(self) -> str | None:
        """The lowest 2xx response, per the plan; then wildcards, then whatever is declared."""
        numeric = sorted(s for s in self.responses if s.isdigit())
        for status in numeric:
            if status.startswith("2"):
                return status
        for status in ("2XX", "2xx", "default"):
            if status in self.responses:
                return status
        return numeric[0] if numeric else None


@dataclass
class _PathEntry:
    template: str
    regex: re.Pattern[str]
    param_names: list[str]
    sort_key: tuple[int, ...]
    operations: dict[str, CompiledRoute] = field(default_factory=dict)


@dataclass
class RouteMatch:
    route: CompiledRoute | None
    path_params: dict[str, str]
    allowed_methods: list[str]


def _compile_template(template: str) -> tuple[re.Pattern[str], list[str], tuple[int, ...]]:
    names: list[str] = []
    pattern = "^"
    cursor = 0
    for match in _PARAM.finditer(template):
        pattern += re.escape(template[cursor : match.start()]) + "([^/]+)"
        names.append(match.group(1))
        cursor = match.end()
    pattern += re.escape(template[cursor:]) + r"\Z"  # `$` would also match before a trailing newline.
    # Compared segment by segment: 0 (static) sorts before 1 (parameter), so /users/me beats
    # /users/{id}, and /a/{x}/c beats /a/{x}/{y}.
    segments = template.strip("/").split("/")
    return re.compile(pattern), names, tuple(1 if "{" in s else 0 for s in segments)


def _bigrams(path: str) -> frozenset[str]:
    text = _PARAM.sub("", path).lower()
    return frozenset(text[i : i + 2] for i in range(len(text) - 1))


def _segment_count(path: str) -> int:
    return len(path.strip("/").split("/"))


class CompiledSpec:
    def __init__(self, doc: dict[str, Any], context: SchemaContext, warnings: list[SpecIssue]):
        self.doc = doc
        self.context = context
        self.warnings = warnings
        self.title = str((doc.get("info") or {}).get("title") or "Untitled API")
        self.version = str(doc.get("openapi"))
        self.routes: dict[str, CompiledRoute] = {}
        self._by_segments: dict[int, list[_PathEntry]] = {}
        self._bigrams: dict[str, frozenset[str]] = {}

    def _add(self, entry: _PathEntry) -> None:
        self._bigrams[entry.template] = _bigrams(entry.template)
        self._by_segments.setdefault(_segment_count(entry.template), []).append(entry)
        for route in entry.operations.values():
            self.routes[route.key] = route

    def _finish(self) -> None:
        for bucket in self._by_segments.values():
            bucket.sort(key=lambda e: e.sort_key)

    def match(self, method: str, path: str) -> RouteMatch:
        path = path if path.startswith("/") else "/" + path
        candidates = [path]
        if len(path) > 1 and path.endswith("/"):
            candidates.append(path.rstrip("/"))
        allowed: list[str] = []
        for candidate in candidates:
            for entry in self._by_segments.get(_segment_count(candidate), ()):
                found = entry.regex.match(candidate)
                if not found:
                    continue
                route = entry.operations.get(method.upper())
                if route is not None:
                    return RouteMatch(route, dict(zip(entry.param_names, found.groups(), strict=True)), [])
                allowed.extend(m for m in entry.operations if m not in allowed)
        return RouteMatch(None, {}, allowed)

    def closest_routes(self, path: str, limit: int = 5) -> list[str]:
        """Similar templates, for 404 messages. Runs on the event loop that serves every mock, so it
        compares precomputed sets: difflib took about 60 ms per miss on a 450-route spec."""
        wanted = _bigrams(path)
        if not wanted:
            return []
        scored = []
        for template, grams in self._bigrams.items():
            shared = len(wanted & grams)
            if shared:
                score = shared / (len(wanted) + len(grams) - shared)
                if score >= 0.2:
                    scored.append((-score, template))
        return [template for _, template in sorted(scored)[:limit]]


def _compile_media(
    context: SchemaContext, content: Any, with_validators: bool
) -> list[MediaType]:
    media: list[MediaType] = []
    if not isinstance(content, dict):
        return media
    for content_type, raw in content.items():
        item = context.resolve(raw)
        schema = item.get("schema")
        entry = MediaType(content_type=str(content_type), schema=schema)
        if "example" in item:
            entry.example, entry.has_example = item["example"], True
        elif isinstance(item.get("examples"), dict) and item["examples"]:
            first = context.resolve(next(iter(item["examples"].values())))
            if "value" in first:
                entry.example, entry.has_example = first["value"], True
        if with_validators and schema is not None:
            entry.validator = context.validator(schema)
        media.append(entry)
    return media


def _compile_param(context: SchemaContext, raw: Any) -> CompiledParam | None:
    item = context.resolve(raw)
    name, location = item.get("name"), item.get("in")
    if not isinstance(name, str) or location not in ("path", "query", "header", "cookie"):
        return None
    schema = item.get("schema")
    if schema is None and isinstance(item.get("content"), dict) and item["content"]:
        schema = context.resolve(next(iter(item["content"].values()))).get("schema")
    style = item.get("style") or ("form" if location in ("query", "cookie") else "simple")
    explode = item.get("explode")
    return CompiledParam(
        name=name,
        location=location,
        required=bool(item.get("required")) or location == "path",
        schema=schema,
        style=str(style),
        explode=bool(explode) if explode is not None else style == "form",
        validator=context.validator(schema) if schema is not None else None,
    )


def _compile_operation(
    context: SchemaContext, method: str, template: str, op: dict[str, Any], shared: list[Any]
) -> CompiledRoute:
    params: dict[tuple[str, str], CompiledParam] = {}
    for raw in [*shared, *(op.get("parameters") or [])]:  # operation level wins
        param = _compile_param(context, raw)
        if param:
            params[(param.name.lower(), param.location)] = param

    body = context.resolve(op.get("requestBody"))
    responses: dict[str, CompiledResponse] = {}
    for status, raw in (op.get("responses") or {}).items():
        response = context.resolve(raw)
        responses[str(status)] = CompiledResponse(
            status=str(status),
            description=str(response.get("description") or ""),
            content=_compile_media(context, response.get("content"), with_validators=False),
            headers=response.get("headers") if isinstance(response.get("headers"), dict) else {},
        )
    return CompiledRoute(
        method=method.upper(),
        template=template,
        summary=str(op.get("summary") or ""),
        description=str(op.get("description") or ""),
        tags=[str(t) for t in (op.get("tags") or [])],
        operation_id=op.get("operationId"),
        params=list(params.values()),
        body_required=bool(body.get("required")),
        body_content=_compile_media(context, body.get("content"), with_validators=True),
        responses=responses,
    )


def _check_version(doc: Any) -> str:
    if not isinstance(doc, dict):
        raise SpecError([SpecIssue("error", "Spec must be a YAML or JSON object.")])
    if "swagger" in doc:
        raise SpecError(
            [
                SpecIssue(
                    "error",
                    "Swagger 2.0 import is planned for v0.2. Convert this spec to OpenAPI 3 first.",
                    path="swagger",
                )
            ]
        )
    version = str(doc.get("openapi") or "")
    if not version.startswith(("3.0", "3.1")):
        raise SpecError(
            [
                SpecIssue(
                    "error",
                    f"Expected 'openapi: 3.0.x' or '3.1.x', found {version or 'nothing'}.",
                    path="openapi",
                )
            ]
        )
    return version


def _check_refs(doc: dict[str, Any]) -> list[SpecIssue]:
    """External refs are a hard error; broken local ones degrade to 'any' with a warning."""
    external: set[str] = set()
    broken: set[str] = set()
    for ref in iter_refs(doc):
        if not ref.startswith("#"):
            external.add(ref)
            continue
        try:
            lookup_pointer(doc, ref)
        except KeyError:
            broken.add(ref)
    if external:
        # Fetching URLs named by an uploaded document would let any uploader probe our network.
        sample = ", ".join(sorted(external)[:3])
        raise SpecError(
            [
                SpecIssue(
                    "error",
                    f"External $refs are not supported; bundle the spec into one file first. "
                    f"Found {len(external)}, for example: {sample}",
                )
            ]
        )
    return [
        SpecIssue("warning", f"$ref does not resolve and will accept anything: {ref}")
        for ref in sorted(broken)[:MAX_SPEC_ISSUES]
    ]


def compile_spec(text: str) -> CompiledSpec:
    """Parse and compile. Raises SpecError when the document cannot be served at all."""
    raw = parse_document(text)
    version = _check_version(raw)
    warnings = _check_refs(raw)
    paths = raw.get("paths") or {}
    if not isinstance(paths, dict):
        raise SpecError([SpecIssue("error", "'paths' must be an object.", path="paths")])

    doc = normalize_30(raw) if version.startswith("3.0") else raw
    context = SchemaContext(doc)
    spec = CompiledSpec(doc, context, warnings)

    for template, raw_item in (doc.get("paths") or {}).items():
        if not str(template).startswith("/"):
            continue  # vendor extensions (x-*) and malformed keys
        item = context.resolve(raw_item)
        regex_, names, sort_key = _compile_template(str(template))
        entry = _PathEntry(str(template), regex_, names, sort_key)
        shared = item.get("parameters") if isinstance(item.get("parameters"), list) else []
        for method in HTTP_METHODS:
            op = item.get(method)
            if isinstance(op, dict):
                entry.operations[method.upper()] = _compile_operation(
                    context, method, str(template), op, shared
                )
        if entry.operations:
            spec._add(entry)
    spec._finish()
    return spec


@dataclass
class ValidationReport:
    ok: bool
    issues: list[SpecIssue]
    title: str | None = None
    openapi_version: str | None = None
    route_count: int = 0
    spec: CompiledSpec | None = None


def validate_text(text: str) -> ValidationReport:
    """Everything the editor needs to know about a spec, without saving it.

    Only problems that stop us serving the spec are errors. Strict-validator findings are
    warnings, because real specs routinely break the letter of OpenAPI and still mock fine.
    """
    try:
        spec = compile_spec(text)
    except SpecError as exc:
        return ValidationReport(ok=False, issues=exc.issues)

    issues = list(spec.warnings)
    raw = parse_document(text)
    cls = OpenAPIV31SpecValidator if spec.version.startswith("3.1") else OpenAPIV30SpecValidator
    try:
        for count, error in enumerate(cls(raw).iter_errors()):
            if count >= MAX_SPEC_ISSUES:
                break
            parts = list(error.absolute_path)
            issues.append(
                SpecIssue(
                    "warning",
                    error.message[:300],
                    path="/".join(str(p) for p in parts) or None,
                    line=line_for_path(text, parts),
                )
            )
    except Exception as exc:  # noqa: BLE001 - the strict validator can trip on odd documents
        issues.append(SpecIssue("warning", f"Strict validation stopped early: {exc}"[:300]))
    if not spec.routes:
        issues.append(SpecIssue("warning", "This spec defines no operations to mock.", "paths"))
    return ValidationReport(
        ok=True,
        issues=issues,
        title=spec.title,
        openapi_version=spec.version,
        route_count=len(spec.routes),
        spec=spec,
    )
