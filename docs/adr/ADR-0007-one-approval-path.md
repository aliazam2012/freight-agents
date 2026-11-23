# ADR-0007: One approval path for everything that leaves

Status: accepted, 2026-11-22.

## Table of Contents

- [Context](#context)
- [Decision](#decision)
- [Consequences](#consequences)

---

## Context

A first draft had a review outbox with its own approve step, which would have meant two approvals for one email and two places to audit.

## Decision

Any SEND tool call waits in the agentcore approval queue. An approval covers one exact call (tool, case and arguments) and is used once. After approval the same call runs through the same hooks, so a send is checked again at the moment it leaves.

## Consequences

One place to review, one audit trail, and no way to approve one message and send another. A changed message needs a new approval.
