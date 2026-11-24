# ADR-0010: Exactly-once orders through idempotency keys and a load fingerprint

Status: accepted 2026-11-23.

## Table of Contents

- [Context](#context)
- [Decision](#decision)
- [Consequences](#consequences)

---

## Context

A duplicate order costs a truck. Duplicates come from three places: a network reply lost after the TMS saved the order, a shipper resending the same tender under a new reference, and a rerun after a crash. The agent platform's own idempotency hook covers the third inside one process, but not the first two.

## Decision

Two layers. Every TMS write carries an `Idempotency-Key` as the IETF HTTPAPI draft describes it (version 09): the client keeps one key across retries, and the TMS replays the first answer for the same key and body, refuses the same key with a different body (422), and answers 409 while the first request runs. The key for a new order derives from the load's fingerprint (shipper, shipper reference, pickup date, origin and destination ZIP codes), and the TMS is searched by that fingerprint before any write, so a resend finds the existing order and a rerun recognizes its own earlier write. A change or cancellation for a load with no order goes to a person.

The client follows the repository's resilience standard: a circuit breaker that a 429 trips for the Retry-After window, a token bucket, full-jitter retries inside a retry budget, and a timeout on every attempt.

## Consequences

Tests prove a lost reply retried with the same key leaves one order, and a per-attempt key would make two. A real TMS without idempotency keys needs the fingerprint search alone, which closes the resend and rerun cases but not a reply lost in flight; that TMS would need a reconciliation job, out of scope here. The mock TMS keeps keys for 24 hours and publishes that policy, as the draft asks.
