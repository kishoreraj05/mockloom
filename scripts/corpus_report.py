#!/usr/bin/env python3
"""Run every corpus spec through the engine and report load rate, timing and output validity."""

from __future__ import annotations

import json
import random
import statistics
import sys
import time
from pathlib import Path

from jsonschema import Draft202012Validator  # noqa: F401
from mockforge_engine import compile_spec, validate_text
from mockforge_engine.generator import Generator
from mockforge_engine.schema import collect_errors

sys.path.insert(0, str(Path(__file__).parent))
from fetch_corpus import MANIFEST, SPECS, filename  # noqa: E402

ROUTE_SAMPLE = 40


def check(item: dict) -> dict:
    text = (SPECS / filename(item)).read_text("utf-8", "replace")
    row = {"name": item["name"], "openapi": item["openapi"], "kb": len(text) // 1024}
    start = time.perf_counter()
    report = validate_text(text)
    row["validate_s"] = round(time.perf_counter() - start, 2)
    row["ok"] = report.ok
    row["issues"] = [i.message[:200] for i in report.issues][:3]
    row["warning_count"] = len(report.issues)
    if not report.ok:
        return row
    start = time.perf_counter()
    spec = compile_spec(text)
    row["compile_s"] = round(time.perf_counter() - start, 2)
    row["routes"] = len(spec.routes)
    checked = invalid = crashed = 0
    bad: list[str] = []
    timings: list[float] = []
    for route in list(spec.routes.values())[:: max(1, len(spec.routes) // ROUTE_SAMPLE)]:
        status = route.default_status()
        if status is None:
            continue
        for media in route.responses[status].content:
            if media.schema is None or media.has_example:
                continue
            checked += 1
            try:
                begin = time.perf_counter()
                value = Generator(spec.context, random.Random(1)).generate(media.schema)
                timings.append((time.perf_counter() - begin) * 1000)
                errors = collect_errors(spec.context.validator(media.schema), value, 2)
            except Exception as exc:  # noqa: BLE001
                crashed += 1
                bad.append(f"CRASH {route.key}: {exc!r}"[:220])
                continue
            if errors:
                invalid += 1
                bad.append(f"{route.key} {errors[0][0]}: {errors[0][1]}"[:220])
    row.update(checked=checked, invalid=invalid, crashed=crashed, bad=bad[:3])
    row["gen_ms_max"] = round(max(timings), 1) if timings else 0
    row["gen_ms_median"] = round(statistics.median(timings), 1) if timings else 0
    return row


def main() -> int:
    rows = []
    for item in json.loads(MANIFEST.read_text()):
        if not (SPECS / filename(item)).exists():
            continue
        try:
            rows.append(check(item))
        except Exception as exc:  # noqa: BLE001 - an unhandled crash is exactly what this hunts
            rows.append({"name": item["name"], "ok": False, "issues": [f"UNHANDLED {exc!r}"[:300]]})
        last = rows[-1]
        print(
            f"{'ok ' if last.get('ok') else 'BAD'} {last['name']:<42} "
            f"{last.get('validate_s', '-'):>6}s routes={last.get('routes', '-'):<5} "
            f"invalid={last.get('invalid', '-')}/{last.get('checked', '-')} "
            f"crash={last.get('crashed', '-')} gen_max={last.get('gen_ms_max', '-')}ms",
            flush=True,
        )
    loaded = sum(1 for r in rows if r.get("ok"))
    checked = sum(r.get("checked", 0) for r in rows)
    invalid = sum(r.get("invalid", 0) for r in rows)
    crashed = sum(r.get("crashed", 0) for r in rows)
    print(f"\nloaded {loaded}/{len(rows)} = {loaded / max(1, len(rows)):.1%}")
    print(f"generated bodies valid {checked - invalid - crashed}/{checked}, crashed {crashed}")
    print(f"slowest validate: {max(r.get('validate_s', 0) for r in rows)}s")
    Path(sys.argv[1] if len(sys.argv) > 1 else "/dev/null").write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
