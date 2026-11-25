# mock-kit

Idempotency-Key handling and problem details shared by the made-up services ([mock-tms](../mock-tms/), [mock-carrier](../mock-carrier/)), following the IETF HTTPAPI draft "The Idempotency-Key HTTP Header Field" (draft 09, read 2026-11-23).

## Table of Contents

- [Behavior](#behavior)

---

## Behavior

- The header value is a quoted Structured Field String.
- The same key with the same request replays the first response.
- A missing or unquoted key is 400; the same key with a different request is 422; a key whose first request is still running is 409. Errors are problem details.
- Keys expire after 24 hours, the published expiry policy.
