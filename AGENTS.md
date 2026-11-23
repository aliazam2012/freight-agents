# Agent Instructions

## Table of Contents

- [Commands](#commands)
- [Rules](#rules)
- [Where Things Go](#where-things-go)

---

## Commands

- `make setup`: install every package into one environment with uv.
- `make check`: ruff, mypy strict and pytest, including the reference evaluation. Run it before every commit.
- `make eval`: the evaluation gate alone. `make demo`: the no-key demo.

## Rules

- Test first: write the failing test, watch it fail, then write the code.
- Never call a paid model API from a test. Use `ScriptedModel` or a cassette.
- Never move a case's state from a tool or a prompt; tools propose, `CaseEngine.fire` decides.
- Any tool that sends outside is `Risk.SEND` and is declared in the taint guard's controls.
- Made-up data only, on `example.com`, `example.net` or `example.org`.

## Where Things Go

Shared behavior goes in `packages/`; anything specific to one application (prompts, tools, its state machine, its policies) stays in that application under `apps/`.
