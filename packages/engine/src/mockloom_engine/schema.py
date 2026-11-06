"""OpenAPI schema helpers: $ref resolution, 3.0-to-JSON-Schema normalisation, validators.

$refs stay in place rather than being expanded into one big document. Full expansion is
exponential on real specs and impossible on circular ones; validators and the data generator
both follow refs on demand instead, so memory stays linear in the size of the spec.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import unquote

import jsonschema
import regex
from jsonschema import Draft202012Validator, FormatChecker, validators

from .limits import REGEX_TIMEOUT_SECONDS

_OPAQUE_KEYS = {"example", "examples", "default", "enum", "const"}


def normalize_30(node: Any) -> Any:
    """Rewrite OpenAPI 3.0's JSON Schema dialect (nullable, boolean exclusives) to 2020-12."""
    if isinstance(node, list):
        return [normalize_30(v) for v in node]
    if not isinstance(node, dict):
        return node
    out = {
        k: (v if k in _OPAQUE_KEYS or k.startswith("x-") else normalize_30(v))
        for k, v in node.items()
    }
    for exclusive, bound in (("exclusiveMinimum", "minimum"), ("exclusiveMaximum", "maximum")):
        flag = out.get(exclusive)
        if flag is True and isinstance(out.get(bound), (int, float)):
            out[exclusive] = out.pop(bound)
        elif isinstance(flag, bool):
            del out[exclusive]
    if out.get("nullable") is True:
        del out["nullable"]
        if isinstance(out.get("type"), str):
            out["type"] = [out["type"], "null"]
            if isinstance(out.get("enum"), list) and None not in out["enum"]:
                out["enum"] = [*out["enum"], None]
        elif "type" not in out:
            return {"anyOf": [out, {"type": "null"}]}
    elif out.get("nullable") is False:
        del out["nullable"]
    return out


def iter_refs(node: Any) -> Iterator[str]:
    """Every $ref in a document, skipping example payloads and vendor extensions."""
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            ref = current.get("$ref")
            if isinstance(ref, str):
                yield ref
            for key, value in current.items():
                if key not in ("example", "examples") and not key.startswith("x-"):
                    stack.append(value)
        elif isinstance(current, list):
            stack.extend(current)


def lookup_pointer(doc: Any, ref: str) -> Any:
    """Follow a local '#/a/b' pointer. Raises KeyError when it does not resolve."""
    if ref in ("#", ""):
        return doc
    node = doc
    for raw in ref.lstrip("#/").split("/"):
        part = unquote(raw).replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            raise KeyError(ref)
    return node


_format_checker = FormatChecker()


def _integer_format(bits: int):
    limit = 2 ** (bits - 1)

    def check(value: Any) -> bool:
        return not isinstance(value, int) or isinstance(value, bool) or -limit <= value < limit

    return check


# OpenAPI's own formats, which jsonschema has no notion of.
_format_checker.checks("int32")(_integer_format(32))
_format_checker.checks("int64")(_integer_format(64))


class SchemaContext:
    """Owns one normalised document and hands out validators that can see its $refs."""

    def __init__(self, doc: dict[str, Any]):
        self.doc = doc
        self._resolved: dict[str, Any] = {}
        context = self

        def safe_pattern(validator, pattern, instance, schema):
            # The stdlib `re` that jsonschema uses can backtrack forever on hostile input.
            if not validator.is_type(instance, "string"):
                return
            try:
                if not regex.search(pattern, instance, timeout=REGEX_TIMEOUT_SECONDS):
                    yield jsonschema.ValidationError(f"{instance!r} does not match {pattern!r}")
            except (regex.error, TimeoutError):
                return

        def tolerant_required(validator, required, instance, schema):
            # `required: true` on a property is a common 3.0 mistake; readOnly fields are not
            # sent by clients, even when they are listed as required.
            if not isinstance(required, list) or not validator.is_type(instance, "object"):
                return
            properties = schema.get("properties") or {}
            for name in required:
                if name in instance:
                    continue
                if isinstance(properties, dict) and context.resolve(properties.get(name)).get(
                    "readOnly"
                ):
                    continue
                yield jsonschema.ValidationError(f"{name!r} is a required property")

        cls = validators.extend(
            Draft202012Validator, {"pattern": safe_pattern, "required": tolerant_required}
        )
        self._root = cls(doc, format_checker=_format_checker)

    def validator(self, schema: Any):
        return self._root.evolve(schema=schema)

    def resolve(self, node: Any) -> dict[str, Any]:
        """Shallowly dereference. Unresolvable or non-object targets come back as {}."""
        seen = 0
        while isinstance(node, dict) and isinstance(node.get("$ref"), str):
            ref = node["$ref"]
            if ref not in self._resolved:
                try:
                    self._resolved[ref] = lookup_pointer(self.doc, ref)
                except KeyError:
                    self._resolved[ref] = {}
            target = self._resolved[ref]
            siblings = {k: v for k, v in node.items() if k != "$ref"}
            node = {**target, **siblings} if siblings and isinstance(target, dict) else target
            seen += 1
            if seen > 32:
                return {}
        return node if isinstance(node, dict) else {}

    def type_set(self, schema: Any, _depth: int = 0) -> set[str]:
        """Every JSON type a schema could accept, seen through refs and combinators."""
        node = self.resolve(schema)
        if _depth > 8:
            return set()
        declared = node.get("type")
        types = {declared} if isinstance(declared, str) else set(declared or [])
        for key in ("allOf", "anyOf", "oneOf"):
            for sub in node.get(key) or []:
                types |= self.type_set(sub, _depth + 1)
        return types


def collect_errors(validator: Any, value: Any, limit: int) -> list[tuple[str, str]]:
    """(json-pointer, message) pairs. A broken schema never counts against the request."""
    errors: list[tuple[str, str]] = []
    try:
        for error in validator.iter_errors(value):
            pointer = "/" + "/".join(str(p) for p in error.absolute_path)
            message = error.message
            errors.append((pointer, message if len(message) <= 240 else message[:237] + "..."))
            if len(errors) >= limit:
                break
    except Exception:  # noqa: BLE001 - unknown types, unresolvable refs, deep recursion
        return errors
    return errors
