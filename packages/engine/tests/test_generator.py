import json
import random

import pytest
from mockloom_engine import Generator, compile_spec
from mockloom_engine.schema import collect_errors


def spec_with(schemas: dict):
    text = json.dumps(
        {
            "openapi": "3.1.0",
            "info": {"title": "T", "version": "1"},
            "paths": {},
            "components": {"schemas": schemas},
        }
    )
    return compile_spec(text)


def gen(schema, schemas=None, seed=1, name=None):
    spec = spec_with(schemas or {})
    return Generator(spec.context, random.Random(seed)).generate(schema, name), spec


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "string", "format": "email"},
        {"type": "string", "format": "uuid"},
        {"type": "string", "format": "date-time"},
        {"type": "string", "format": "date"},
        {"type": "string", "minLength": 50},
        {"type": "string", "maxLength": 2},
        {"type": "string", "pattern": "^[A-Z]{3}-[0-9]{4}$"},
        {"type": "string", "pattern": "^a+$", "maxLength": 5},
        {"type": "integer", "minimum": 5, "maximum": 6},
        {"type": "integer", "exclusiveMinimum": 5, "exclusiveMaximum": 7},
        {"type": "integer", "multipleOf": 7, "minimum": 10, "maximum": 20},
        {"type": "number", "minimum": 0.5, "maximum": 0.75},
        {"type": "number", "multipleOf": 0.5, "minimum": 1, "maximum": 3},
        {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 5},
        {"type": "array", "items": {"enum": ["a", "b", "c"]}, "uniqueItems": True, "maxItems": 3},
        {"type": "array", "maxItems": 0, "items": {"type": "string"}},
        {"type": "object", "required": ["a"], "properties": {"a": {"type": "boolean"}}},
        {"type": "object", "additionalProperties": {"type": "integer"}},
        {"type": "object", "required": ["undeclared"]},
        {"enum": [1, "two", None]},
        {"const": "fixed"},
        {"type": ["integer", "null"]},
        {"oneOf": [{"type": "string"}, {"type": "integer"}]},
        {"anyOf": [{"type": "null"}, {"type": "boolean"}]},
        {"allOf": [{"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]},
                   {"properties": {"b": {"type": "integer"}}, "required": ["b"]}]},
    ],
)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_output_conforms(schema, seed):
    value, spec = gen(schema, seed=seed)
    assert collect_errors(spec.context.validator(schema), value, 5) == []


def test_same_seed_same_output_and_different_seed_differs():
    schema = {"type": "object", "properties": {"email": {"type": "string"}, "n": {"type": "integer"}}}
    first, _ = gen(schema, seed=7)
    second, _ = gen(schema, seed=7)
    third, _ = gen(schema, seed=8)
    assert first == second and first != third


def test_field_name_heuristics():
    value, _ = gen(
        {
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "avatarUrl": {"type": "string"},
                "firstName": {"type": "string"},
                "created_at": {"type": "string"},
                "age": {"type": "integer"},
            },
        }
    )
    assert "@" in value["email"]
    assert value["avatarUrl"].startswith("http")
    assert value["firstName"].isalpha() or " " in value["firstName"]
    assert value["created_at"].endswith("Z")
    assert 18 <= value["age"] <= 90


def test_examples_come_first():
    value, _ = gen({"type": "object", "properties": {"a": {"type": "string", "example": "chosen"}}})
    assert value == {"a": "chosen"}
    value, _ = gen({"type": "string", "examples": ["first", "second"]})
    assert value == "first"


def test_defaults_contradicting_type_are_ignored():
    value, _ = gen({"type": "string", "default": False})
    assert isinstance(value, str)


def test_write_only_fields_are_left_out():
    value, _ = gen(
        {"type": "object", "properties": {"password": {"type": "string", "writeOnly": True}}}
    )
    assert value == {}


def test_circular_ref_terminates_and_conforms():
    schemas = {
        "Node": {
            "type": "object",
            "required": ["value"],
            "properties": {
                "value": {"type": "string"},
                "children": {"type": "array", "items": {"$ref": "#/components/schemas/Node"}},
            },
        }
    }
    schema = {"$ref": "#/components/schemas/Node"}
    value, spec = gen(schema, schemas)
    assert "children" in value
    assert collect_errors(spec.context.validator(schema), value, 5) == []


def test_required_cycle_terminates():
    schemas = {
        "A": {"type": "object", "required": ["b"], "properties": {"b": {"$ref": "#/components/schemas/B"}}},
        "B": {"type": "object", "required": ["a"], "properties": {"a": {"$ref": "#/components/schemas/A"}}},
    }
    value, _ = gen({"$ref": "#/components/schemas/A"}, schemas)
    assert isinstance(value, dict)


def test_wide_cyclic_graph_stays_small():
    props = {f"p{i}": {"$ref": f"#/components/schemas/S{(i + 1) % 30}"} for i in range(30)}
    schemas = {f"S{i}": {"type": "object", "properties": props} for i in range(30)}
    value, _ = gen({"$ref": "#/components/schemas/S0"}, schemas)
    assert len(json.dumps(value)) < 1024 * 1024


def test_allof_with_nullable_keeps_the_real_type():
    # A pattern real specs use, seen in the corpus.
    text = json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "T", "version": "1"},
            "paths": {},
            "components": {"schemas": {"L": {"type": "integer", "minimum": 0}}},
        }
    )
    spec = compile_spec(text)
    from mockloom_engine.schema import normalize_30

    schema = normalize_30({"allOf": [{"nullable": True}, {"$ref": "#/components/schemas/L"}]})
    assert isinstance(Generator(spec.context, random.Random(1)).generate(schema), int)
