---
title: The Idempotency-Key HTTP Header Field (IETF draft, version 09)
source_url: https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/
publisher: IETF HTTPAPI working group, Internet-Draft draft-ietf-httpapi-idempotency-key-header-09 (2026-11-21)
read_on: 2026-11-23
---

Plain-language summary of a working-group draft; drafts change before they become standards.

## The header

Idempotency-Key is an Item Structured Header Field whose value must be a String, so it is sent quoted, for example "8e03978e-40d5-43e8-bc93-6894a57f9324". A key must not be reused for a request with a different payload.

## Retries and fingerprints

A resource may store a fingerprint of each request's payload with its key. A retry of a completed request should get a response consistent with that request having completed. A key reused with a different payload fails, and does not return the original result.

## Errors

A required key that is missing gets 400. A key reused with a different payload gets 422. A key whose first request is still being processed gets 409. Each comes with a problem description (RFC 9457).

## Expiry

A resource may expire keys after a time, and should publish that policy in its documentation.
