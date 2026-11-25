# Changelog

## Table of Contents

- [Unreleased](#unreleased)

---

## Unreleased

Toward v0.1.0.

- Platform packages: model interface with Anthropic and OpenAI adapters, scripted model and record-and-replay; typed tools and the hook pipeline (validation, state allowlist, taint, recipient policy, idempotency, approval, redaction, size cap, audit); the agent loop with turn, tool-call and cost limits; the state engine with an append-only event store and timers; sourced claim rules with BM25 retrieval; email, outbound transport and TMS integrations; golden-set evaluation with a CI gate; OpenTelemetry spans and a cost meter.
- claims-intake: triage, extraction with TMS lookup, the 49 CFR 370.3 minimum check and the filing window, approved requests for missing details, and a 7-day reply timer.
- A no-key demo over a made-up inbox, a CLI to review and approve sends, architecture and decision records, and a threat model.
- volume-forecast (milestone v0.6, built early because it needs no API key): seeded synthetic carrier volume; seasonal-naive, Holt-Winters and global gradient-boosted models; a rolling-origin backtest with WAPE, MASE and bias; split conformal ranges with measured coverage; run ids and a dated report; the `freight-forecast` CLI; a planner agent over four read-only tools with a grounding grader and a 16-question golden set.
- Intel Macs stay on a published cryptography wheel (49 and later ship none for them).
- tms-orders (milestone v0.4, built before v0.2 because its results need no API key): X12 envelope reader and writer, 204 parser and 990 writer from two published partner guides, PDF and email extraction through one strict tool, sourced validation rules (USPS, 49 CFR 172, 23 USC 127, trailer payloads) with windows compared in UTC, a location master, a mock TMS with Idempotency-Key semantics, a resilient client, exactly-once submits, the `freight-orders` CLI, a read-only MCP server, and a golden and red-team evaluation in CI.
- The clean-room scan matches phone numbers by their 3-3-4 grouping, so decimals no longer read as phones.
- carrier-filing (milestone v0.3): claim packets from claims-intake handoffs with a 370.3 cover letter; API, portal (headless Chromium) and email channels that each file once; the 370.5 and 370.9 deadlines as timers that fire once; approved follow-ups that cite their section; carrier replies read through one model tool; the `freight-filing` CLI and a read-only MCP server; a 34-scenario evaluation in CI.
- Shared: Idempotency-Key handling moved to services/mock-kit and the resilient HTTP layer to integrations, used by both the TMS and carrier clients.
- incident-bot (milestone v0.5): a severity policy sourced from PagerDuty's guide and the Google SRE book, cadence reminders that reset on every update, a chat port with an in-memory Slack and a contract-tested slack_sdk adapter, a Bolt app for Socket Mode, cited runbooks, approved customer updates, a blameless postmortem from the repository template, the `freight-incidents` CLI and MCP server, and a 20-scenario evaluation in CI.
- Platform stores (statecore events, agentcore approvals, idempotency and audit) can be called from a server's worker threads: one shared connection, a lock per method.
