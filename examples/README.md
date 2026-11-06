# Examples

Ready-made workspaces to try MockLoom with, and to copy from. They are listed on the home page,
where **Open example** creates the workspace with its rules, and **Start from this spec** loads the
spec into the form so you can edit it first.

| Example | Good for | Files |
|---|---|---|
| **Task Tracker** (OpenAPI 3.1) | Start here. The smallest one, and the best to copy. | [spec](specs/task-tracker.yaml), [rules](rules/task-tracker) |
| **Petstore** (OpenAPI 3.0) | The classic sample: priorities, paywalls, body and schema matching. | [spec](specs/petstore.yaml), [rules](rules/petstore) |
| **Payments API** (OpenAPI 3.0) | Checkout errors: declined cards, rate limits, slow responses. | [spec](specs/payments.yaml), [rules](rules/payments) |
| **Code Hosting API** (OpenAPI 3.0) | Nested routes, search and permission errors. | [spec](specs/code-hosting.yaml), [rules](rules/code-hosting) |

The Payments and Code Hosting APIs are fictional. They don't describe any real service.

## Using one as a starting point

1. **Copy the closest spec** and rename its routes and schemas to match your API.
2. **Upload it** and call the mock URL. Without any rules, every route already returns generated data.
3. **Add a rule per UI state** you need to test. Copy the closest file from `rules/`, or use the rule
   builder. Rule files are the same JSON that `POST /api/workspaces/{slug}/rules` accepts.

## Adding an example

Add `specs/<id>.yaml` and `rules/<id>/*.json`, then add an entry to [`catalog.json`](catalog.json). The
test suite sends every request listed under `try` and checks its status and matched rule, so an
example can't quietly stop working.
