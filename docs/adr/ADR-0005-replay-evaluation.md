# ADR-0005: Evaluation on recorded runs, gated in CI

Status: accepted, 2026-11-22.

## Table of Contents

- [Context](#context)
- [Decision](#decision)
- [Consequences](#consequences)

---

## Context

Live model calls in CI cost money, vary between runs, and fail when a provider is down. The prompt standard asks for temperature 0, but current Claude models reject sampling parameters, so determinism cannot come from the request.

## Decision

A golden set with deterministic graders. CI runs it in reference mode (scripted correct turns, plus red-team turns that fall for every injection) to check the pipeline and the guards, and in recorded mode (a real model's turns, recorded once with approval, replayed offline) to check the model. Floors in floors.toml fail the build.

## Consequences

CI is free and repeatable, and every README number traces to a dated report. Recordings go stale when prompts change; re-recording is a deliberate, paid step.
