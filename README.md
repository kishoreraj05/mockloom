# MockLoom

Upload an OpenAPI 3.x spec and get a live mock server, with no code. Responses change based on the
request, so you can test empty lists, validation errors and paywalls before the real backend exists.

## Run it

You only need Docker:

```bash
docker build -t mockloom .
```

```bash
docker run -p 127.0.0.1:8000:8000 -v mockloom-data:/data mockloom
```

Open <http://localhost:8000>, find **Task Tracker** under **Examples**, and choose **Open example**. Your mock is live:

```bash
curl "http://localhost:8000/mock/task-tracker/tasks?status=done"
```

There are four [examples](examples) to try and copy from, each with ready-made rules and a list of requests to send.

Your workspaces are kept in the `mockloom-data` volume. The command only accepts connections from your own computer,
because [there is no authentication yet](#configuration). To use Postgres instead, add
`-e MOCKLOOM_DATABASE_URL=postgresql+psycopg://user:pass@host/db`.

**From source:** with Python 3.11 to 3.13 and Node 22 or newer, run `make setup` and then `make serve`.

## What it does

| | |
|---|---|
| **Spec import** | OpenAPI 3.0 and 3.1, YAML or JSON, up to 5 MB. Versions are kept, and a new one goes live without a restart. |
| **Generated responses** | Spec examples first, then fake data that honours the schema and field names. A per-workspace seed keeps output repeatable. |
| **Rules** | "If query `status=empty`, return 200 with `[]`." Match on path, query, headers, cookies or body, with templated responses. |
| **Validation** | Requests that break the spec get a 400 in RFC 7807 problem JSON. Can be turned off per workspace. |
| **Live log** | Every call with its matched rule and response, streamed to the browser. Turn any request into a rule. |
| **Chaos** | Latency, error rate, forced status and dropped connections, globally or per route. |
| **Use in your app** | Every route shows its absolute URL, with copyable cURL, JavaScript and Python requests using dummy values that pass validation, plus an example response and an example request for each rule. |

Keyboard: `/` search routes, `n` new rule, `l` focus the log.

## Rules

Rules are JSON, so the UI can build them without code. [`rule.schema.json`](packages/engine/rule.schema.json) is
the full schema, and [`examples/rules`](examples/rules) has worked examples for each sample API.

```json
{
  "name": "Empty cart",
  "route": "GET /cart",
  "priority": 10,
  "when": { "all": [
    { "source": "query", "field": "state", "op": "eq", "value": "empty" },
    { "source": "header", "field": "x-user-tier", "op": "in", "value": ["free", "trial"] }
  ]},
  "then": { "status": 200, "body": { "items": [], "total": 0 }, "delay_ms": 300 }
}
```

- **Order:** lower `priority` numbers run first, and the first match decides. Ties keep creation order.
- **Sources:** `path`, `query`, `header`, `cookie`, `body` (JSONPath, such as `$.items[0].sku`).
- **Operators:** `eq`, `neq`, `in`, `contains`, `regex`, `gt`, `lt`, `exists`, `matches_schema`.
- **Templates:** `{{request.path.id}}`, `{{request.query.q}}`, `{{request.body.name}}`, `{{request.headers['x-a']}}`,
  `{{faker.email}}`, `{{now}}`. A string that is only one `{{ }}` keeps its type, so `id` comes back as the number `42`.
  Filters and inline `if`/`else` work. Loops, arithmetic and calls are refused when the rule is saved.
- **No `body`:** the response is generated from the spec's schema for that status.

## Layout

```
packages/engine   Pure Python: spec compiler, generator, rule engine, pipeline. No web framework.
apps/api          FastAPI: management API, the /mock catch-all route, WebSocket log, storage.
apps/web          React workspace: routes, rule builder, spec editor, chaos board, request log.
examples/         Sample APIs for the gallery: specs, rules and a catalog of requests to try.
tests/corpus      Manifest of 57 public specs. The specs themselves are downloaded, not committed.
```

## Configuration

| Variable | Default | |
|---|---|---|
| `MOCKLOOM_DATABASE_URL` | `sqlite:///./mockloom.db` | For Postgres: `postgresql+psycopg://user:pass@host/db`, with the `postgres` extra installed. |
| `MOCKLOOM_RATE_LIMIT_PER_MINUTE` | `0` (off) | Per workspace. For public deployments. |
| `MOCKLOOM_WEB_DIST` | `apps/web/dist` | Where the built frontend is. |

**Run one server process.** Compiled specs, rules and the log stream are held in memory, so extra workers would
serve stale rules.

**There is no authentication yet** (planned for v1.0), and anyone who can reach the server can edit every workspace.
Keep it on localhost or a trusted network.

## Known limits

- External `$ref`s are refused rather than fetched, because fetching URLs named by an uploaded file lets uploaders
  probe your network. Bundle multi-file specs into one file first.
- A spec with problems still loads if it can be served. Strict OpenAPI findings show up as warnings.
- Generated data follows the schema except where a spec contradicts itself, or uses a regex feature the generator
  can't reverse, such as lookaheads.
- Multipart bodies are accepted but not validated.
- Security schemes aren't enforced. A mock answers without credentials.
- Authorization, cookie and API key headers appear as `[redacted]` in the log. Rules can still match on them.

## Development

```bash
make test         # engine, API and frontend unit tests, including a Schemathesis fuzz of the mock
make test-corpus  # downloads the public spec corpus and runs it
make e2e          # Playwright, full loop in a real browser
make lint
make gen          # after changing the API or rule models
```

See [CONTRIBUTING.md](CONTRIBUTING.md).
