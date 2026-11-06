from pathlib import Path

import pytest
from mockloom_engine import compile_spec

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def petstore_text() -> str:
    return (ROOT / "examples" / "specs" / "petstore.yaml").read_text()


@pytest.fixture(scope="session")
def petstore(petstore_text):
    return compile_spec(petstore_text)
