"""Parse spec text into plain JSON-compatible Python, safely, and map paths back to lines."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import yaml

from .limits import MAX_SPEC_BYTES, MAX_YAML_EXPANDED_NODES

try:
    _Loader: type = yaml.CSafeLoader
except AttributeError:  # pragma: no cover - libyaml is absent on some platforms
    _Loader = yaml.SafeLoader


@dataclass(frozen=True)
class SpecIssue:
    severity: str  # "error" | "warning"
    message: str
    path: str | None = None
    line: int | None = None


class SpecError(Exception):
    """The document cannot be served. Carries every problem we could identify."""

    def __init__(self, issues: list[SpecIssue]):
        super().__init__("; ".join(i.message for i in issues))
        self.issues = issues


def _fail(message: str, line: int | None = None) -> SpecError:
    return SpecError([SpecIssue("error", message, line=line)])


def _check_expansion(root: yaml.Node) -> None:
    """Reject YAML alias bombs and recursive aliases before anything walks the expanded tree."""
    weights: dict[int, int] = {}
    active: set[int] = set()

    def weigh(node: yaml.Node) -> int:
        key = id(node)
        if key in weights:
            return weights[key]
        if key in active:
            raise _fail("YAML contains a recursive alias, which cannot be represented as JSON.")
        active.add(key)
        total = 1
        if isinstance(node, yaml.MappingNode):
            for k, v in node.value:
                total += weigh(k) + weigh(v)
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                total += weigh(item)
        active.discard(key)
        if total > MAX_YAML_EXPANDED_NODES:
            raise _fail("YAML aliases expand to too many nodes; refusing to load this document.")
        weights[key] = total
        return total

    weigh(root)


def _to_plain(value: Any) -> Any:
    """YAML gives us int keys (`200:`) and date objects; JSON-world code expects neither."""
    if isinstance(value, dict):
        return {_key(k): _to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_plain(v) for v in value]
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def _key(key: Any) -> str:
    if isinstance(key, bool):
        return "true" if key else "false"
    if isinstance(key, (dt.datetime, dt.date)):
        return key.isoformat()
    return str(key)


def parse_document(text: str) -> Any:
    if len(text.encode("utf-8", "replace")) > MAX_SPEC_BYTES:
        raise _fail(f"Spec is larger than the {MAX_SPEC_BYTES // (1024 * 1024)} MB limit.")
    if not text.strip():
        raise _fail("Spec is empty.")
    try:
        if text.lstrip().startswith(("{", "[")):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass  # Could still be YAML flow style; let the YAML parser report the error.
        loader = _Loader(text)
        try:
            node = loader.get_single_node()
            if node is None:
                raise _fail("Spec is empty.")
            _check_expansion(node)
            return _to_plain(loader.construct_document(node))
        finally:
            loader.dispose()
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark
        line = mark.line + 1 if mark else None
        raise _fail(f"Could not parse YAML: {exc.problem or exc}", line=line) from exc
    except yaml.YAMLError as exc:
        raise _fail(f"Could not parse YAML: {exc}") from exc
    except RecursionError as exc:
        raise _fail("Document is nested too deeply to parse.") from exc


def line_for_path(text: str, path: Iterable[str | int]) -> int | None:
    """Best-effort 1-based line of a JSON path, used for inline editor markers."""
    try:
        node = yaml.compose(text, Loader=_Loader)
    except (yaml.YAMLError, RecursionError):
        return None
    if node is None:
        return None
    line = node.start_mark.line + 1
    for part in path:
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                if str(getattr(key_node, "value", "")) == str(part):
                    line, node = key_node.start_mark.line + 1, value_node
                    break
            else:
                return line
        elif isinstance(node, yaml.SequenceNode):
            try:
                node = node.value[int(part)]
            except (ValueError, IndexError):
                return line
            line = node.start_mark.line + 1
        else:
            return line
    return line
