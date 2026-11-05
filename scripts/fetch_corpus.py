#!/usr/bin/env python3
"""Download the public spec corpus into tests/corpus/specs (gitignored).

Specs are fetched instead of vendored because each carries its own licence. The manifest pins
every file by SHA-256, so a corpus run is repeatable and a changed upstream file is reported.

    python scripts/fetch_corpus.py            # download what the manifest lists
    python scripts/fetch_corpus.py --select   # rebuild the manifest from the APIs.guru index
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "tests" / "corpus"
MANIFEST = ROOT / "manifest.json"
SPECS = ROOT / "specs"
INDEX = "https://api.apis.guru/v2/list.json"
MAX_BYTES = 5 * 1024 * 1024  # The product's own upload limit.

# Well known APIs, because these are the specs people will actually try first.
NAMED = [
    "stripe.com", "twilio.com:api", "slack.com", "spotify.com", "github.com:api.github.com",
    "digitalocean.com", "plaid.com", "box.com", "asana.com", "discourse.org", "zoom.us",
    "gitlab.com", "circleci.com", "netlify.com", "vercel.com", "sendgrid.com", "linode.com",
    "docusign.net", "nytimes.com:article_search", "xkcd.com", "openai.com", "mailchimp.com",
    "pandascore.co", "vimeo.com", "ably.io:platform", "1password.com:events", "adyen.com:CheckoutService",
]  # fmt: skip
TARGET_30 = 45
TARGET_31 = 15


def get(url: str, limit: int = MAX_BYTES + 1) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "mockforge-corpus-fetch"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed sources
        return response.read(limit)


def select() -> None:
    index = json.loads(get(INDEX, limit=64 * 1024 * 1024))

    def stable(name: str) -> str:
        return hashlib.sha256(name.encode()).hexdigest()

    def entry(name: str) -> dict:
        api = index[name]
        version = api["versions"][api["preferred"]]
        return {"name": name, "url": version["swaggerUrl"], "openapi": version.get("openapiVer", "")}

    names = [n for n in NAMED if n in index]
    chosen = [entry(n) for n in names]
    for prefix, target in (("3.0", TARGET_30), ("3.1", TARGET_31)):
        have = sum(c["openapi"].startswith(prefix) for c in chosen)
        for name in sorted(index, key=stable):
            if have >= target:
                break
            item = entry(name)
            if name not in names and item["openapi"].startswith(prefix):
                chosen.append(item)
                names.append(name)
                have += 1
    final = []
    for item in chosen:
        if not item["openapi"].startswith(("3.0", "3.1")):
            continue
        try:
            data = get(item["url"])
        except Exception as exc:  # noqa: BLE001
            print(f"skip {item['name']}: {exc}", file=sys.stderr)
            continue
        if len(data) > MAX_BYTES:
            print(f"skip {item['name']}: over the 5 MB upload limit", file=sys.stderr)
            continue
        final.append({**item, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    final.sort(key=lambda i: i["name"])
    MANIFEST.write_text(json.dumps(final, indent=1) + "\n")
    print(f"manifest: {len(final)} specs")


def filename(item: dict) -> str:
    suffix = ".yaml" if item["url"].endswith((".yaml", ".yml")) else ".json"
    return hashlib.sha256(item["name"].encode()).hexdigest()[:12] + suffix


def fetch() -> int:
    SPECS.mkdir(parents=True, exist_ok=True)
    problems = 0
    for item in json.loads(MANIFEST.read_text()):
        target = SPECS / filename(item)
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == item["sha256"]:
            continue
        try:
            data = get(item["url"])
        except Exception as exc:  # noqa: BLE001
            print(f"failed {item['name']}: {exc}", file=sys.stderr)
            problems += 1
            continue
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            print(f"changed upstream, using new content: {item['name']}", file=sys.stderr)
        target.write_bytes(data)
    print(f"corpus ready in {SPECS} ({problems} failed)")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--select", action="store_true")
    args = parser.parse_args()
    if args.select:
        select()
    raise SystemExit(fetch())
