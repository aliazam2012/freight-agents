# ADR-0006: MCP servers for integrations in v0.3

Status: accepted, 2026-11-22.

## Table of Contents

- [Context](#context)
- [Decision](#decision)
- [Consequences](#consequences)

---

## Context

Serving integrations over MCP lets any MCP client (Claude Code, Codex, other agents) use them behind the same hooks. claims-intake v0.1 has one integration of each kind and no outside client yet.

## Decision

v0.1 ships the integrations as Python interfaces. v0.3 (carrier-filing, three integration styles) adds MCP servers that run every call through the same hook pipeline, write-safety guards included.

## Consequences

v0.1 stays small. The hook pipeline is already transport-independent, so the MCP layer is an adapter, not a rewrite.
