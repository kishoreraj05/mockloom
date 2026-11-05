#!/usr/bin/env python3
"""Write the rule JSON Schema to packages/engine/rule.schema.json. CI checks that it is current."""

import json
from pathlib import Path

from mockforge_engine import rule_json_schema

target = Path(__file__).resolve().parent.parent / "packages" / "engine" / "rule.schema.json"
target.write_text(json.dumps(rule_json_schema(), indent=2) + "\n")
print(f"wrote {target}")
