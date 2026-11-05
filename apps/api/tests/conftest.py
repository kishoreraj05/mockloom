import os
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient
from mockforge_api.main import create_app
from mockforge_api.settings import Settings

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def settings(tmp_path):
    # MOCKFORGE_TEST_DATABASE_URL points the same suite at Postgres in CI.
    url = os.getenv("MOCKFORGE_TEST_DATABASE_URL") or f"sqlite:///{tmp_path}/test.db"
    return Settings(database_url=url, web_dist=tmp_path / "no-dist", log_flush_seconds=0.02)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def petstore_text():
    return (ROOT / "examples" / "specs" / "petstore.yaml").read_text()


_counter = {"n": 0}


@pytest.fixture
def workspace(client, petstore_text):
    # Unique slugs, so a shared Postgres database can run the suite repeatedly.
    _counter["n"] += 1
    slug = f"pets-{os.getpid()}-{_counter['n']}"
    response = client.post(
        "/api/workspaces", json={"name": "Pets", "slug": slug, "spec_text": petstore_text}
    )
    assert response.status_code == 201, response.text
    yield response.json()["slug"]
    client.delete(f"/api/workspaces/{slug}")


@contextmanager
def serve(app):
    """Run an app under real uvicorn, for behaviour that only exists on a real socket."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
