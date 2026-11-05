"""The MVP loop from the plan, end to end: upload a spec, get a URL, add a rule, watch the log."""

import time


def test_upload_mock_rule_log(client, petstore_text):
    created = client.post("/api/workspaces", json={"name": "My Shop API", "spec_text": petstore_text})
    assert created.status_code == 201
    workspace = created.json()
    slug = workspace["slug"]
    assert slug == "my-shop-api" or slug.startswith("my-shop-api-")
    assert workspace["route_count"] == 6

    url = f"{workspace['mock_path']}/pets"
    assert client.get(url).json()["items"] is not None

    rule = client.post(
        f"/api/workspaces/{slug}/rules",
        json={
            "name": "Empty",
            "route": "GET /pets",
            "priority": 10,
            "when": {"all": [{"source": "query", "field": "status", "op": "eq", "value": "empty"}]},
            "then": {"status": 200, "body": {"items": [], "total": 0}},
        },
    )
    assert rule.status_code == 201

    response = client.get(url, params={"status": "empty"})
    assert response.json() == {"items": [], "total": 0}
    assert response.headers["x-mockforge-rule"] == "Empty"

    logs = client.get(f"/api/workspaces/{slug}/logs").json()
    assert [entry["rule_name"] for entry in logs] == [None, "Empty"]
    assert logs[1]["path"].endswith("?status=empty")
    client.delete(f"/api/workspaces/{slug}")


def test_log_streams_over_websocket(client, workspace):
    with client.websocket_connect(f"/api/workspaces/{workspace}/logs/stream") as socket:
        client.get(f"/mock/{workspace}/pets/7")
        entry = socket.receive_json()[0]
    assert entry["method"] == "GET" and entry["path"] == "/pets/7"
    assert entry["status"] == 200 and entry["route_key"] == "GET /pets/{id}"
    assert entry["overhead_ms"] >= 0


def test_websocket_refuses_other_origins(client, workspace):
    from starlette.websockets import WebSocketDisconnect

    try:
        with client.websocket_connect(
            f"/api/workspaces/{workspace}/logs/stream",
            headers={"origin": "https://evil.example", "host": "localhost:8000"},
        ):
            raise AssertionError("connection should have been refused")
    except WebSocketDisconnect as exc:
        assert exc.code == 4403


def test_logs_reach_the_database_and_survive_restart(settings, petstore_text):
    from fastapi.testclient import TestClient
    from mockforge_api.main import create_app

    with TestClient(create_app(settings)) as first:
        slug = first.post(
            "/api/workspaces",
            json={"name": "Restart", "slug": f"restart-{time.time_ns()}", "spec_text": petstore_text},
        ).json()["slug"]
        first.get(f"/mock/{slug}/pets")
    with TestClient(create_app(settings)) as second:
        assert second.get(f"/mock/{slug}/pets/1").status_code == 200  # spec reloaded from storage
        entries = second.get(f"/api/workspaces/{slug}/logs").json()
        assert "/pets" in [entry["path"] for entry in entries]
        # Browsers read a timestamp with no timezone as local time, so the clock would be wrong.
        assert all(entry["ts"].endswith(("Z", "+00:00")) for entry in entries)
        second.delete(f"/api/workspaces/{slug}")


def test_offline_really_drops_the_connection(settings, petstore_text):
    import httpx
    import pytest
    from fastapi.testclient import TestClient
    from mockforge_api.main import create_app

    from .conftest import serve

    app = create_app(settings)
    slug = f"offline-{time.time_ns()}"
    with TestClient(app) as client:
        client.post("/api/workspaces", json={"name": "O", "slug": slug, "spec_text": petstore_text})
        client.put(f"/api/workspaces/{slug}/chaos", json={"offline": True})
    with serve(app) as url:
        with pytest.raises(httpx.TransportError):
            httpx.get(f"{url}/mock/{slug}/pets", timeout=5)
        entry = httpx.get(f"{url}/api/workspaces/{slug}/logs").json()[-1]
        assert entry["status"] == 0 and "offline" in entry["chaos"]
        httpx.delete(f"{url}/api/workspaces/{slug}")


def test_stream_does_not_lose_rows_under_load(client, workspace):
    with client.websocket_connect(f"/api/workspaces/{workspace}/logs/stream") as socket:
        for index in range(300):
            client.get(f"/mock/{workspace}/pets/{index}")
        received = []
        while len(received) < 300:
            received.extend(socket.receive_json())
    assert [entry["path"] for entry in received] == [f"/pets/{index}" for index in range(300)]
    assert received[0]["ts"].endswith(("Z", "+00:00"))


def test_paging_back_past_the_ring_buffer(settings, petstore_text):
    from dataclasses import replace

    from fastapi.testclient import TestClient
    from mockforge_api.main import create_app

    slug = f"paging-{time.time_ns()}"
    with TestClient(create_app(replace(settings, log_ring_size=5))) as client:
        client.post("/api/workspaces", json={"name": "P", "slug": slug, "spec_text": petstore_text})
        for index in range(12):
            client.get(f"/mock/{slug}/pets/{index}")
        time.sleep(0.2)  # Let the batched writer reach the database.

        url = f"/api/workspaces/{slug}/logs"
        latest = client.get(url).json()
        assert [e["path"] for e in latest] == [f"/pets/{i}" for i in range(7, 12)]

        page = client.get(url, params={"before": latest[0]["ts"], "limit": 4}).json()
        assert [e["path"] for e in page] == [f"/pets/{i}" for i in range(3, 7)]

        last = client.get(url, params={"before": page[0]["ts"], "limit": 4}).json()
        assert [e["path"] for e in last] == [f"/pets/{i}" for i in range(0, 3)]
        client.delete(f"/api/workspaces/{slug}")


def test_workspaces_with_the_same_name_created_at_once_all_succeed(settings):
    from concurrent.futures import ThreadPoolExecutor

    import httpx
    from fastapi.testclient import TestClient
    from mockforge_api.main import create_app

    from .conftest import serve

    app = create_app(settings)
    name = f"Race {time.time_ns()}"
    with TestClient(app):
        pass
    with serve(app) as url:

        def create(_):
            return httpx.post(f"{url}/api/workspaces", json={"name": name}, timeout=30)

        with ThreadPoolExecutor(8) as pool:
            responses = list(pool.map(create, range(8)))
        assert [r.status_code for r in responses] == [201] * 8, [r.text for r in responses]
        slugs = {r.json()["slug"] for r in responses}
        assert len(slugs) == 8
        for slug in slugs:
            httpx.delete(f"{url}/api/workspaces/{slug}")
