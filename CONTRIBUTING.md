# Contributing

`make setup`, then `make test`. See the [README](README.md#development) for the other commands.

## Good first issues

- **New rule operators:** add to `Operator` and `CompiledCondition.matches` in `packages/engine/src/mockforge_engine/rules.py`, and to `OPERATORS` in `apps/web/src/lib/rules.ts`.
- **Faker mappings:** add field names to `_STRING_NAMES` or `_INTEGER_NAMES` in `generator.py`.
- **Example APIs:** see [Adding an example](examples/README.md#adding-an-example).
- **Corpus failures:** run `python scripts/corpus_report.py`. A real spec that won't load is always a bug worth filing.

## Rules of the road

- **The engine stays pure.** `packages/engine` does no I/O and imports no web framework.
- **The mock path never touches the database.** It reads from memory, and logs are written in batches.
- **User input never runs as code.** Templates are limited by an AST allowlist and regexes have timeouts. Anything that widens either needs a test showing it can't hang the event loop, because one slow request blocks every mock on the server.
- **The API is the contract.** After changing `schemas.py` or the rule models, run `make gen` and commit the result. CI fails if they drift.
- **Database changes need a migration** in `apps/api/src/mockforge_api/migrations/versions`, and must work on both SQLite and Postgres.
