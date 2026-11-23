# ADR-0004: Provider-neutral model layer

Status: accepted, 2026-11-22.

## Table of Contents

- [Context](#context)
- [Decision](#decision)
- [Consequences](#consequences)

---

## Context

Teams choose models by price, quality and contract, and change them. Code written against one provider's message format is costly to move.

## Decision

One Model interface and one set of conversation types. Adapters for the Anthropic Messages API (strict tools, explicit effort, no sampling parameters, refusal fallbacks on Opus and Sonnet, returned blocks sent back unchanged) and the OpenAI Responses API (strict function tools, store=False with encrypted reasoning returned). Provider-native blocks travel in a native field that only the same adapter reads.

## Consequences

Switching provider is a constructor argument, and the evaluation suite compares them on equal terms. Provider features without a neutral equivalent are added to the adapter, not to the applications.
