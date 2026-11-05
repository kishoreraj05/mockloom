"""Run the public spec corpus. Needs `python scripts/fetch_corpus.py` first; CI does that."""

import json
import random
import sys
from pathlib import Path

import pytest
from mockforge_engine import MockEngine, RawRequest, compile_spec, validate_text
from mockforge_engine.generator import Generator
from mockforge_engine.schema import collect_errors

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_corpus import MANIFEST, SPECS, filename  # noqa: E402

ITEMS = [i for i in json.loads(MANIFEST.read_text()) if (SPECS / filename(i)).exists()]
pytestmark = [
    pytest.mark.corpus,
    pytest.mark.skipif(not ITEMS, reason="corpus not downloaded; run scripts/fetch_corpus.py"),
]


def text_of(item):
    return (SPECS / filename(item)).read_text("utf-8", "replace")


def test_success_metric_load_rate():
    """Plan: 95% of valid specs in the corpus load without errors."""
    failures = {}
    for item in ITEMS:
        report = validate_text(text_of(item))
        if not report.ok:
            failures[item["name"]] = report.issues[0].message
    assert 1 - len(failures) / len(ITEMS) >= 0.95, failures


def test_corpus_has_both_versions():
    versions = {i["openapi"][:3] for i in ITEMS}
    assert versions == {"3.0", "3.1"}
    assert len(ITEMS) >= 50


def test_generated_output_matches_its_schema():
    """Spec examples are off here: this measures our walker, not the accuracy of spec authors.

    The remainder are specs that contradict themselves, like `type: array` with string enums.
    """
    total = invalid = 0
    for item in ITEMS:
        spec = compile_spec(text_of(item))
        for route in spec.routes.values():
            status = route.default_status()
            for media in (route.responses[status].content if status else []):
                if media.schema is None:
                    continue
                total += 1
                value = Generator(spec.context, random.Random(1), use_examples=False).generate(media.schema)
                invalid += bool(collect_errors(spec.context.validator(media.schema), value, 1))
    assert total > 2000
    assert 1 - invalid / total >= 0.94


@pytest.mark.parametrize("item", ITEMS, ids=lambda i: i["name"])
def test_every_route_answers_without_crashing(item):
    spec = compile_spec(text_of(item))
    engine = MockEngine(spec, seed=1, validate=False)
    for route in list(spec.routes.values())[:60]:
        path = route.template.replace("{", "").replace("}", "")
        result = engine.handle(RawRequest(route.method, path))
        assert result.status != 500 or result.source != "error" or "too large" in result.body.decode()
