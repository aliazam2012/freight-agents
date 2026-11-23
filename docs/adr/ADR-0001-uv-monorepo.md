# ADR-0001: One uv workspace for the platform and every application

Status: accepted, 2026-11-22.

## Table of Contents

- [Context](#context)
- [Decision](#decision)
- [Consequences](#consequences)

---

## Context

Six applications share the same tools, hooks, state engine, model layer and evaluation. Splitting them across repositories would mean version bumps and coordinated releases for every platform change, and a reviewer would need seven repositories to see one design.

## Decision

One repository, one uv workspace, one lockfile. Platform packages live under packages/, applications under apps/, all importable under the freight_agents namespace. Dependencies point one way: llm, then agentcore and telemetry, then the rest, then applications.

## Consequences

A platform change and its effect on every application land in one pull request and one CI run. The cost is that a package cannot be released on its own schedule; if that need appears, the packages are already separate distributions and can move out.
