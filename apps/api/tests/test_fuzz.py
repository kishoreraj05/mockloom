"""Schemathesis fuzzes the mock against its own spec over real HTTP, as the plan asks.

Whatever it sends, the mock must not crash, valid requests must be accepted, invalid ones must be
rejected, and what comes back must match the spec.
"""

from pathlib import Path

import pytest
import schemathesis
import yaml
from fastapi.testclient import TestClient
from hypothesis import HealthCheck
from hypothesis import settings as hypothesis_settings
from mockloom_api.main import create_app
from mockloom_api.settings import Settings
from schemathesis.checks import not_a_server_error
from schemathesis.specs.openapi.checks import (
    content_type_conformance,
    negative_data_rejection,
    positive_data_acceptance,
    response_schema_conformance,
)

from .conftest import serve

ROOT = Path(__file__).resolve().parents[3]
TEXT = (ROOT / "examples" / "specs" / "petstore.yaml").read_text()
schema = schemathesis.openapi.from_dict(yaml.safe_load(TEXT))


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    directory = tmp_path_factory.mktemp("fuzz")
    app = create_app(Settings(database_url=f"sqlite:///{directory}/fuzz.db"))
    with TestClient(app) as client:
        created = client.post("/api/workspaces", json={"name": "F", "slug": "fuzz", "spec_text": TEXT})
        assert created.status_code == 201

    with serve(app) as url:
        yield f"{url}/mock/fuzz"


@schema.parametrize()
@hypothesis_settings(max_examples=30, deadline=None, suppress_health_check=list(HealthCheck), database=None)
def test_mock_conforms_to_its_own_spec(case, base_url):
    response = case.call(base_url=base_url)
    checks = [
        not_a_server_error,
        content_type_conformance,
        response_schema_conformance,
        positive_data_acceptance,
    ]
    # Unknown query parameters are accepted on purpose. OpenAPI does not forbid them, and real
    # front-ends send them (cache busters, analytics); rejecting them would only break apps.
    if "x-schemathesis-unknown-property" not in (case.query or {}):
        checks.append(negative_data_rejection)
    case.validate_response(response, checks=checks)
