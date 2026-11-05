#!/usr/bin/env python3
"""Measure mock overhead over real HTTP. Plan target: under 10 ms p95 per request.

Compares each scenario with a bare endpoint on the same server, so the figure is what MockForge
adds, not the cost of HTTP itself.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from fastapi import Response
from mockforge_api.main import create_app
from mockforge_api.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
REQUESTS = 2000
CONCURRENCY = 8


async def measure(client: httpx.AsyncClient, make_request) -> list[float]:
    timings: list[float] = []
    queue = iter(range(REQUESTS))

    async def worker() -> None:
        for index in queue:
            started = time.perf_counter()
            response = await make_request(client, index)
            timings.append((time.perf_counter() - started) * 1000)
            assert response.status_code < 500, response.text

    await asyncio.gather(*(worker() for _ in range(CONCURRENCY)))
    return sorted(timings[REQUESTS // 10 :])  # The first requests warm the caches.


def p95(values: list[float]) -> float:
    return values[int(len(values) * 0.95)]


async def run(base: str, slug: str) -> None:
    async with httpx.AsyncClient(base_url=base, timeout=30) as client:
        rule = {
            "name": "Echo",
            "route": "GET /pets/{id}",
            "when": {"all": [{"source": "path", "field": "id", "op": "gt", "value": 500}]},
            "then": {"body": {"id": "{{request.path.id}}", "email": "{{faker.email}}"}},
        }
        assert (await client.post(f"/api/workspaces/{slug}/rules", json=rule)).status_code == 201
        new_pet = {"name": "Rex", "price": 5}
        scenarios = {
            "baseline: bare endpoint": lambda c, i: c.get("/__baseline"),
            "generated, same path (cached)": lambda c, i: c.get(f"/mock/{slug}/pets"),
            "generated, new path every time": lambda c, i: c.get(f"/mock/{slug}/pets/{i % 500}"),
            "rule with templates": lambda c, i: c.get(f"/mock/{slug}/pets/{501 + i}"),
            "POST, body validated": lambda c, i: c.post(f"/mock/{slug}/pets", json=new_pet),
        }
        baseline = None
        print(f"{'scenario':<34}{'p50 ms':>9}{'p95 ms':>9}{'added p95':>11}")
        for name, request in scenarios.items():
            values = await measure(client, request)
            baseline = baseline if baseline is not None else p95(values)
            added = p95(values) - baseline
            print(f"{name:<34}{statistics.median(values):>9.2f}{p95(values):>9.2f}{added:>11.2f}")
        logs = (await client.get(f"/api/workspaces/{slug}/logs")).json()
        internal = sorted(entry["overhead_ms"] for entry in logs)
        print(f"\nServer-side overhead, last {len(internal)} logged: p95 {p95(internal):.2f} ms")


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        app = create_app(Settings(database_url=f"sqlite:///{directory}/bench.db"))

        @app.get("/__baseline", include_in_schema=False)
        async def baseline() -> Response:
            return Response(json.dumps({"ok": True}), media_type="application/json")

        # The SPA catch-all was registered first, so move the baseline in front of it.
        app.router.routes.insert(0, app.router.routes.pop())

        server = uvicorn.Server(uvicorn.Config(app, port=18790, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        while not server.started:
            time.sleep(0.05)
        spec = (ROOT / "examples" / "specs" / "petstore.yaml").read_text()
        created = httpx.post(
            "http://127.0.0.1:18790/api/workspaces",
            json={"name": "Bench", "slug": "bench", "spec_text": spec},
        )
        assert created.status_code == 201, created.text
        asyncio.run(run("http://127.0.0.1:18790", "bench"))
        server.should_exit = True
        thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
