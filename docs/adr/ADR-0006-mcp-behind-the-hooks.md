# ADR-0006: MCP for integrations, behind the same hooks

Status: accepted 2026-11-22; revised the same day to ship MCP in v0.1 instead of v0.3.

## Table of Contents

- [Context](#context)
- [Decision](#decision)
- [Consequences](#consequences)

---

## Context

Serving tools over MCP lets any MCP client (Claude Code, Codex, other agents) use them. The risk is a second path into the system that skips the guards agents go through. The first version of this decision deferred MCP to v0.3; it was brought forward so the write-safety design is visible from the first release.

## Decision

A generic bridge (`packages/mcp`) turns a router into an MCP server. Every `tools/call` is routed to a toolkit (registry, hooks, context) and run through the same `run_tool` as an agent's call. claims-intake exposes reads (case, pending sends, shipment, claim rules) and one write request, `request_missing_info`, which runs the internal drafting tool and stops in the approval queue. No MCP tool approves or sends.

## Consequences

An MCP client has no more power than an agent, and its calls appear in the same audit log under the agent name `mcp`. Each application chooses what to expose; approval stays a person's action through the CLI.
