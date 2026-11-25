# ADR-0011: One filing per claim on every channel

Status: accepted 2026-11-24.

## Table of Contents

- [Context](#context)
- [Decision](#decision)
- [Consequences](#consequences)

---

## Context

Carriers take claims three ways: a REST API, a web portal, or a claims mailbox. A claim filed twice costs a carrier's time and the claimant's credibility, and every channel can fail between the carrier accepting the claim and the claimant recording that it did: a reply lost in flight, a crash, an expired session. The channels give very different tools for safety: an API can take an idempotency key, a portal takes none, and email has only the sent mail.

## Decision

One `CarrierChannel` interface (`find(reference)`, `file(packet, documents)`), with each channel's own guarantee:

- **API.** Search the carrier by our claim reference, then write with an Idempotency-Key derived from the carrier and the reference, on the shared resilient HTTP layer (one key across retries, breaker, budget, timeouts).
- **Portal.** Headless Chromium searches "my claims" before any submit. A filing counts only when the confirmation page shows a claim number; an expired session or a form missing a field raises before anything is submitted, and the next attempt searches again.
- **Email.** The message a person approves is exactly the one sent; the sent mail, dated in the letter, is the record a rerun finds.

The packet is refused before any channel runs if it lacks a 49 CFR 370.3 element.

## Consequences

The evaluation plays a crash after the carrier accepted the claim on every channel, a lost reply, an expired session and a changed form; each ends with exactly one filing, or none for the changed form. A portal that changes its layout breaks the adapter loudly instead of filing half a claim. The email channel cannot tell a delivered claim from a sent one; the 30-day acknowledgement reminder is the backstop.
