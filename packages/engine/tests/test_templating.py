import pytest
from faker import Faker
from mockloom_engine.templating import TemplateError, check_templates, render, template_context


def ctx(**request):
    base = {"path": {}, "query": {}, "headers": {}, "cookies": {}, "body": None, "method": "GET", "url": "/"}
    return template_context({**base, **request}, Faker())


def test_lone_expression_keeps_native_type():
    assert render("{{request.path.id}}", ctx(path={"id": 42})) == 42
    assert render("{{request.body}}", ctx(body={"a": [1]})) == {"a": [1]}


def test_mixed_template_is_a_string():
    assert render("pet-{{request.path.id}}", ctx(path={"id": 42})) == "pet-42"


def test_renders_nested_values_and_keys():
    out = render({"a": ["{{request.query.q}}"], "{{request.query.q}}": 1}, ctx(query={"q": "x"}))
    assert out == {"a": ["x"], "x": 1}


def test_missing_values_are_null_not_errors():
    assert render("{{request.query.nope}}", ctx()) is None
    assert render("{{request.body.a.b.c}}", ctx(body={})) is None


def test_dict_method_names_read_keys():
    assert render("{{request.query.items}}", ctx(query={"items": "5"})) == "5"
    assert render("{{request.query.items}}", ctx()) is None


def test_faker_and_now():
    assert "@" in render("{{faker.email}}", ctx())
    assert render("{{now}}", ctx()).endswith("Z")


def test_filters_and_inline_if():
    assert render("{{request.query.q | upper}}", ctx(query={"q": "x"})) == "X"
    assert render("{{request.query.q | default('fallback')}}", ctx()) == "fallback"
    assert render("{{'yes' if request.query.q == 'a' else 'no'}}", ctx(query={"q": "a"})) == "yes"


@pytest.mark.parametrize(
    "bad",
    [
        "{{ 9**9**9 }}",
        "{{ 'a' * 1000000000 }}",
        "{% for i in range(99999) %}{% for j in range(99999) %}x{% endfor %}{% endfor %}",
        "{{ request.__class__ }}",
        "{{ request._private }}",
        "{{ faker.__init__ }}",
        "{{ faker._faker }}",
        "{{ faker.binary }}",
        "{{ ''.__class__.__mro__ }}",
        "{{ request.query.get('x') }}",
        "{{ lipsum }}",
        "{{ cycler }}",
        "{{ self }}",
        "{{ config }}",
        "{% include 'x' %}",
        "{% import 'x' as y %}",
        "{% set x = 1 %}",
        "{{ 'x' | center(1000000000) }}",
        "{{ [1,2,3] }}",
        "{% unclosed",
    ],
)
def test_dangerous_templates_are_rejected_when_saved(bad):
    with pytest.raises(TemplateError):
        check_templates({"body": [bad]})


def test_plain_text_is_not_a_template():
    check_templates({"a": "no braces here", "b": 5})
    assert render("no braces here", ctx()) == "no braces here"
