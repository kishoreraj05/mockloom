.PHONY: setup dev-api dev-web serve test test-corpus e2e lint gen

# Python 3.11 to 3.13. Newer versions may not have wheels for every dependency yet.
PYTHON ?= python3.13

setup:
	$(PYTHON) -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e packages/engine -e "apps/api[dev,postgres]"
	cd apps/web && npm install

# Run these two in separate terminals, then open http://localhost:5173
dev-api:
	.venv/bin/uvicorn mockloom_api.asgi:app --reload --port 8000
dev-web:
	cd apps/web && npm run dev

# One server, on http://localhost:8000, serving the built app.
serve:
	cd apps/web && npm run build
	.venv/bin/uvicorn mockloom_api.asgi:app --port 8000

test:
	.venv/bin/pytest packages/engine/tests apps/api/tests
	cd apps/web && npm test

test-corpus:
	.venv/bin/python scripts/fetch_corpus.py
	.venv/bin/pytest tests/test_corpus.py

e2e:
	cd apps/web && npm run build && npm run e2e

lint:
	.venv/bin/ruff check .
	cd apps/web && npm run typecheck

# Regenerate what is derived from the Python code: the rule schema and the TypeScript client.
gen:
	.venv/bin/python scripts/export_rule_schema.py
	.venv/bin/python scripts/export_openapi.py
	cd apps/web && npm run gen:api
