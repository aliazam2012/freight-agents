# Checklist: Code Review

What a reviewer checks on every pull request, in order of what costs most when missed.

## Table of Contents

- [Safety](#safety)
- [Correctness](#correctness)
- [Evaluation](#evaluation)
- [Design](#design)
- [Docs and Hygiene](#docs-and-hygiene)

---

## Safety

- A new tool declares its risk. A new send tool is declared in the taint guard's controls and reaches the approval queue.
- No path lets a model, an MCP client or a tool move a case's state except `CaseEngine.fire`.
- Untrusted text (email, attachments, model output) never reaches a recipient, an amount, a URL or a file path without a validator.
- No secret, real address or real company in code, fixtures or docs.

## Correctness

- A test failed before the change and passes after it. For a bug, the test reproduces the bug.
- Errors are results, not crashes: tool failures, refusals, budget limits, unknown cases.
- Writes are idempotent where a retry is possible.

## Evaluation

- `make eval` passes. A change to prompts, tools or graders says how the metrics moved.
- A new behavior that a person would notice has a golden case.

## Design

- Shared behavior lives in `packages/`; one application's policy lives in its `apps/` folder.
- A decision someone will ask "why" about has an ADR.
- The change is the smallest that solves the problem; unrelated cleanup is its own pull request.

## Docs and Hygiene

- README and docs match the code. Numbers come from a committed report.
- Markdown has a Table of Contents, no em dashes, plain words.
