# mock-carrier

A made-up carrier claims service for carrier-filing: a JSON API with Idempotency-Key semantics (shared with the mock TMS through [mock-kit](../mock-kit/)) and a server-rendered portal. The [OpenAPI file](openapi.json) covers the API and is checked by a test.

## Table of Contents

- [API](#api)
- [Portal](#portal)
- [Acting as the Carrier](#acting-as-the-carrier)

---

## API

| Method and path | Does |
|---|---|
| `POST /api/claims` | File a claim; needs an Idempotency-Key; returns the carrier's claim number |
| `GET /api/claims?reference=` | Claims, optionally for one claimant reference |
| `GET /api/claims/{number}` | One claim, with acknowledgement and disposition dates |

## Portal

Built to behave like a real carrier portal: a sign-in, a claim form with uploads, a confirmation page showing the claim number and the date received, a "my claims" list, sessions that expire after 30 minutes, and no idempotency, so a double submit files twice. `create_app(..., portal_without=("amount_usd",))` drops form fields, the way a redesign might.

## Acting as the Carrier

Routes under `/admin` (outside the OpenAPI file) acknowledge, pay, decline or make an offer on a claim, dated by the app's clock. Tests and the evaluation use them; nothing in the agents calls them.
