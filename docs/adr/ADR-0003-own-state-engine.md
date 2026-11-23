# ADR-0003: Own state engine over SQLite before a workflow engine

Status: accepted, 2026-11-22.

## Table of Contents

- [Context](#context)
- [Decision](#decision)
- [Consequences](#consequences)

---

## Context

Claim cases live for months (a carrier has 120 days to decide) and need timers, an audit trail and guarded transitions. Durable workflow engines such as Temporal solve this at scale but add a server to run and learn.

## Decision

A state machine with guarded transitions over an append-only SQLite event log, with timers as events. The current view of a case is always rebuilt from its events.

## Consequences

Everything runs on a laptop with no server, and the log is the single truth. Throughput and multi-worker scheduling are limited; when an application needs them, the CaseEngine interface is the seam where a workflow engine would go.
