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
