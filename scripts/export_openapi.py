#!/usr/bin/env python3
"""Write FastAPI's OpenAPI document to apps/web/src/api/openapi.json for openapi-typescript."""

import json
import os
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory() as directory:
    os.environ["MOCKLOOM_DATABASE_URL"] = f"sqlite:///{directory}/export.db"
    from mockloom_api.main import create_app

    document = create_app().openapi()

target = Path(__file__).resolve().parent.parent / "apps" / "web" / "src" / "api" / "openapi.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(document, indent=2) + "\n")
print(f"wrote {target}")
