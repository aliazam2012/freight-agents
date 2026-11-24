# mock-tms

A made-up TMS order API for tests and demos. It exists so tms-orders has a real HTTP write to make safe. The [OpenAPI file](openapi.json) is committed and a test fails if the app drifts from it.

## Table of Contents

- [Endpoints](#endpoints)
- [Idempotency](#idempotency)
- [Run It](#run-it)

---

## Endpoints

| Method and path | Does |
|---|---|
| `POST /orders` | Create an order from `{fingerprint, tender_reference, order}`; needs an Idempotency-Key |
| `GET /orders?fingerprint=` | Orders, optionally for one load |
| `GET /orders/{order_id}` | One order |
| `PATCH /orders/{order_id}` | `{action: change or cancel, tender_reference, order}`; needs an Idempotency-Key; a cancelled order cannot change (422) |

## Idempotency

Writes follow the IETF HTTPAPI draft "The Idempotency-Key HTTP Header Field" (draft 09, read 2026-11-23):

- The header value is a Structured Field String, so it is quoted: `Idempotency-Key: "create:4f1c..."`.
- The same key with the same request replays the first response.
- A missing or unquoted key is 400; the same key with a different request is 422; a key whose first request is still running is 409. Errors are problem details (`application/problem+json`).
- Keys expire after 24 hours. That is this service's published expiry policy, as the draft asks.

## Run It

```bash
uv run --all-packages python -m freight_agents.mock_tms.app       # rewrite openapi.json
uv run --all-packages uvicorn freight_agents.mock_tms.app:create_app --factory --port 8070
```

The second command needs uvicorn, which is not a dependency; `freight-orders` runs this app in process by default.
