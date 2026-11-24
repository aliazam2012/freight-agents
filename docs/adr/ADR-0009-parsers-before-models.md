# ADR-0009: Parsers before models for load tenders

Status: accepted 2026-11-23.

## Table of Contents

- [Context](#context)
- [Decision](#decision)
- [Consequences](#consequences)

---

## Context

Load tenders arrive three ways: X12 EDI 204 files, PDF rate confirmations and plain email. EDI is a formal syntax with an envelope that can be checked; PDF and email are free text in many layouts. A model can read all three, but a model reading EDI adds cost, latency and a way to be wrong to a job code does exactly.

## Decision

EDI is parsed by code (`x12.py` for the envelope, `edi204.py` for the 204), with every count and control number checked and a typed error naming the segment. Only PDF text and email go to the model, and the model has one tool, `record_order`, whose fields stay null when the document does not state them. Everything after extraction is code: validation with sourced rules, the TMS write, and the reply, all through the hook pipeline. The model never calls a write or a send.

## Consequences

EDI accuracy is measured without a model and is exact for well-formed files; a malformed file is refused with the segment named, not guessed at. Model cost and risk apply only to free text. Prompt injection can reach only the extraction step, where the worst a fooled model can do is record a wrong value; the location master, exact-match submit and recipient policy limit what that value can change, and the residual gap is written into the threat model.
