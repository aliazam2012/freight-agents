# ADR-0002: Own agent loop instead of an agent framework

Status: accepted, 2026-11-22.

## Table of Contents

- [Context](#context)
- [Decision](#decision)
- [Consequences](#consequences)

---

## Context

The interesting parts of this system are the hooks, the state engine and the approval path. Agent frameworks hide the loop that calls tools, which is exactly where those parts attach, and tie the code to one framework's release cycle.

## Decision

A small agent loop (agentcore/agent.py) over the providers' native tool calling: one model turn, every tool call through run_tool, all results back in one message, limits on turns, tool calls and dollars.

## Consequences

About 150 lines own the loop, and every guard is visible and tested. Features a framework would bring (memory, multi-agent handoffs) are added only when an application needs them.
