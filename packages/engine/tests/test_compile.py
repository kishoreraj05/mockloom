import json

import pytest
from mockforge_engine import SpecError, compile_spec, validate_text
from mockforge_engine.loader import parse_document


def minimal(paths="{}", version="3.0.3", extra=""):
    return f"openapi: {version}\ninfo: {{title: T, version: '1'}}\npaths: {paths}\n{extra}"


def test_compiles_petstore(petstore):
    assert set(petstore.routes) >= {"GET /pets", "POST /pets", "GET /pets/{id}", "DELETE /pets/{id}"}
    assert petstore.title == "Petstore"


@pytest.mark.parametrize(
    "path, expected, params",
    [
        ("/pets", "/pets", {}),
        ("/pets/", "/pets", {}),
        ("/pets/42", "/pets/{id}", {"id": "42"}),
        ("/pets/mine", "/pets/mine", {}),  # Static beats parameter, whatever the spec's order.
    ],
)
def test_route_matching(petstore, path, expected, params):
    match = petstore.match("GET", path)
    assert match.route.template == expected
    assert match.path_params == params


def test_static_segment_priority_is_positional():
    spec = compile_spec(
        minimal(
            """
  /a/{x}/{y}: {get: {responses: {'200': {description: ok}}}}
  /a/{x}/c: {get: {responses: {'200': {description: ok}}}}
  /{w}/b/c: {get: {responses: {'200': {description: ok}}}}
"""
        )
    )
    assert spec.match("GET", "/a/b/c").route.template == "/a/{x}/c"
    assert spec.match("GET", "/a/b/z").route.template == "/a/{x}/{y}"
    assert spec.match("GET", "/q/b/c").route.template == "/{w}/b/c"


def test_template_with_regex_characters_is_literal():
    spec = compile_spec(minimal("{'/v1.0/files/{name}.json': {get: {responses: {'200': {description: ok}}}}}"))
    assert spec.match("GET", "/v1.0/files/a.json").path_params == {"name": "a"}
    assert spec.match("GET", "/v1x0/files/a.json").route is None


def test_method_mismatch_reports_allowed(petstore):
    match = petstore.match("PUT", "/pets")
    assert match.route is None and set(match.allowed_methods) == {"GET", "POST"}


def test_closest_routes_suggests_likely_typos(petstore):
    assert petstore.closest_routes("/pet")[0] == "/pets"
    assert "/store/inventory" in petstore.closest_routes("/store/inventry")
    assert petstore.closest_routes("/zzzzzz") == []
    assert petstore.closest_routes("/") == []


def test_path_level_parameters_are_inherited_and_overridable(petstore):
    assert [p.name for p in petstore.routes["GET /pets/{id}"].params] == ["id"]
    spec = compile_spec(
        minimal(
            """
  /x:
    parameters:
      - {name: q, in: query, schema: {type: string}}
    get:
      parameters:
        - {name: q, in: query, required: true, schema: {type: integer}}
      responses: {'200': {description: ok}}
"""
        )
    )
    params = spec.routes["GET /x"].params
    assert len(params) == 1 and params[0].required


def test_integer_response_keys_from_yaml_are_handled():
    spec = compile_spec(minimal("{/x: {get: {responses: {200: {description: ok}}}}}"))
    assert spec.routes["GET /x"].default_status() == "200"


def test_unquoted_yaml_dates_become_strings():
    doc = parse_document("example: 2024-01-15\nwhen: 2024-01-15T10:00:00Z\n")
    assert doc["example"] == "2024-01-15"
    json.dumps(doc)


def test_default_status_is_lowest_2xx():
    spec = compile_spec(
        minimal(
            "{/x: {get: {responses: {'404': {description: a}, '201': {description: b}, "
            "'200': {description: c}}}}}"
        )
    )
    assert spec.routes["GET /x"].default_status() == "200"


def test_swagger_2_gets_a_clear_message():
    report = validate_text('swagger: "2.0"\ninfo: {title: T, version: "1"}\npaths: {}\n')
    assert not report.ok and "v0.2" in report.issues[0].message


def test_openapi_2x_version_is_rejected():
    assert not validate_text("openapi: 2.0.0\npaths: {}").ok


def test_external_refs_are_refused_and_never_fetched():
    text = minimal(
        "{/x: {get: {responses: {'200': {description: ok, content: {application/json: "
        "{schema: {$ref: 'http://169.254.169.254/latest/meta-data'}}}}}}}}"
    )
    report = validate_text(text)
    assert not report.ok and "External $refs" in report.issues[0].message


def test_broken_local_ref_is_a_warning_and_still_serves():
    text = minimal(
        "{/x: {get: {responses: {'200': {description: ok, content: {application/json: "
        "{schema: {$ref: '#/components/schemas/Nope'}}}}}}}}"
    )
    report = validate_text(text)
    assert report.ok
    assert any("does not resolve" in i.message for i in report.issues)


def test_yaml_syntax_error_has_a_line_number():
    report = validate_text("openapi: 3.0.3\ninfo:\n  title: [unclosed\npaths: {}\n")
    assert not report.ok and report.issues[0].line is not None


def test_strict_validator_findings_are_warnings_with_lines():
    text = "openapi: 3.0.3\ninfo: {title: T, version: '1'}\npaths:\n  /x:\n    get:\n      responses: {}\n"
    report = validate_text(text)
    assert report.ok and report.issues
    assert all(i.severity == "warning" for i in report.issues)


def test_yaml_alias_bomb_is_refused():
    lines = ["a0: &a0 [x, x, x, x, x, x, x, x, x, x]"]
    for level in range(1, 12):
        refs = ", ".join([f"*a{level - 1}"] * 10)
        lines.append(f"a{level}: &a{level} [{refs}]")
    with pytest.raises(SpecError, match="too many nodes"):
        parse_document("\n".join(lines))


def test_recursive_yaml_alias_is_refused():
    with pytest.raises(SpecError, match="recursive alias"):
        parse_document("a: &a\n  b: *a\n")


def test_size_limit():
    with pytest.raises(SpecError, match="larger than"):
        parse_document("a: " + "x" * (5 * 1024 * 1024 + 1))


def test_deep_nesting_does_not_crash():
    report = validate_text("[" * 200_000)
    assert not report.ok


@pytest.mark.parametrize("text", ["", "   ", "null", "42", "[]", "just a string"])
def test_non_documents_are_rejected_politely(text):
    assert not validate_text(text).ok


def test_nullable_30_is_normalised():
    spec = compile_spec(
        minimal(
            "{}",
            extra="components: {schemas: {A: {type: string, nullable: true, enum: [a]}, "
            "B: {type: integer, minimum: 1, exclusiveMinimum: true}}}",
        )
    )
    schemas = spec.doc["components"]["schemas"]
    assert schemas["A"]["type"] == ["string", "null"] and None in schemas["A"]["enum"]
    assert schemas["B"]["exclusiveMinimum"] == 1 and "minimum" not in schemas["B"]


def test_property_called_nullable_is_left_alone():
    spec = compile_spec(
        minimal("{}", extra="components: {schemas: {A: {properties: {nullable: {type: boolean}}}}}")
    )
    assert spec.doc["components"]["schemas"]["A"]["properties"]["nullable"] == {"type": "boolean"}


def test_openapi_31_type_arrays_compile():
    spec = compile_spec(
        minimal(
            "{/x: {get: {responses: {'200': {description: ok, content: {application/json: "
            "{schema: {type: [string, 'null']}}}}}}}}",
            version="3.1.0",
        )
    )
    assert "GET /x" in spec.routes
