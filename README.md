# freight-agents

Agent workflows for freight operations on one shared platform: typed tools with pre and post hooks, a state engine the model cannot bypass, provider-neutral models, and evaluation as the release gate.

```bash
git clone https://github.com/aliazam2012/freight-agents && cd freight-agents
make setup && make demo
```

The demo needs no API key. It runs a made-up claims inbox through the real workflow (every hook, the state engine, the approval queue) with recorded reference turns in place of a model, then shows the emails waiting for a person to approve.

Freight operations run on email: claims, load tenders, carrier disputes. An agent that reads that email can save hours, and it can also file the wrong claim, email the wrong person, or follow instructions an attacker wrote into a message. This repository shows how to build those agents so the dangerous parts stay out of the model's hands: the model proposes, deterministic code decides, and a person approves anything that leaves.

## Table of Contents

- [What It Does](#what-it-does)
- [Skills Shown](#skills-shown)
- [How It Works](#how-it-works)
- [Applications](#applications)
- [Results](#results)
- [Run With a Real Model](#run-with-a-real-model)
- [Use It From Claude Code or Codex](#use-it-from-claude-code-or-codex)
- [Layout](#layout)
- [Requirements](#requirements)
- [Tests](#tests)
- [Contributing, Security, License](#contributing-security-license)

---

## What It Does

- **Tools stay simple; hooks hold the policy.** Each tool is a typed function marked read, write or send. Hooks run around every call: validation, state allowlists, untrusted-input checks, idempotency, approval, redaction, size caps, audit.
- **The model never moves a case.** Cases live in an append-only event log with guarded transitions and timers. A tool proposes; the state engine accepts or refuses.
- **Untrusted email cannot steer an action.** Every value from an email is tainted; a send whose recipient came from email text is refused, wherever the text hid (body, subject, attachment name).
- **Nothing leaves without a person.** Outbound email waits in an approval queue; an approval covers one exact message, once.
- **Any model, same behavior.** One interface with adapters for the Anthropic Messages API and the OpenAI Responses API; a scripted model and record-and-replay for tests.
- **Measured, not claimed.** A golden set with deterministic graders gates every change in CI, including red-team cases where the model falls for an injection on purpose and the guards must still hold.
- **Sourced domain rules.** Claim rules come from 49 CFR Part 370 and 49 U.S.C. 14706, read at the source, retrieved with citations.
- **Documents to transactions, exactly once.** Load tenders by EDI 204, PDF or email become one validated TMS order: code parses EDI, the model only reads free text, and writes carry idempotency keys a lost reply cannot duplicate.
- **Classic machine learning, backtested.** Volume forecasts beat a seasonal-naive baseline in a rolling-origin backtest, with prediction ranges whose coverage is measured; the planner agent quotes only figures its tools return.

## Skills Shown

Each row points at the code or the public issue that proves it. Shipped means merged, tested and gated in CI; planned means an issue with acceptance criteria.

| Skill | Where it shows | Status |
|---|---|---|
| Evaluation as the release gate | [golden set and floors](apps/claims-intake/evals/), `make eval` in CI, red-team cases, [reports](apps/claims-intake/evals/reports/) | Shipped; real-model results in [v0.1.0](https://github.com/aliazam2012/freight-agents/issues/10) |
| Reliable agent workflows | [state engine](packages/statecore/), idempotent writes and the approval queue in [agentcore](packages/agentcore/) | Shipped |
| Defense against prompt injection | taint and recipient guards, [threat model](docs/THREAT-MODEL.md) | Shipped |
| MCP with write safety | [MCP bridge](packages/mcp/), [claims MCP server](apps/claims-intake/src/freight_agents/claims_intake/mcp_server.py), [ADR-0006](docs/adr/ADR-0006-mcp-behind-the-hooks.md) | Shipped |
| Provider-neutral models | [Anthropic and OpenAI adapters](packages/llm/), [ADR-0004](docs/adr/ADR-0004-provider-neutral-models.md) | Shipped; live runs in [v0.1.0](https://github.com/aliazam2012/freight-agents/issues/10) |
| Coding agents in the repository | [AGENTS.md](AGENTS.md), Claude Code and Codex setup above | Shipped |
| Observability and cost control | [telemetry](packages/telemetry/), `--trace`, budgets, cost and latency per case | Shipped |
| Sourced domain knowledge | [claim rules with citations](packages/knowledge/) | Shipped |
| Clean room and supply chain | purity gate, private denylist, gitleaks, pip-audit, CodeQL, pinned actions | Shipped |
| Running an engineering team | [ADRs](docs/adr/), [review checklist](docs/CHECKLIST-code-review.md), [release runbook](docs/RUNBOOK-release.md), [postmortem template](docs/TPL-postmortem.md), [milestones](https://github.com/aliazam2012/freight-agents/milestones) | Shipped |
| Vision AI | damage-assessor | Planned, [v0.2](https://github.com/aliazam2012/freight-agents/issues/11) |
| Integrations and durable timers | [carrier-filing](apps/carrier-filing/): one claim filing per API, portal (headless Chromium) or email channel, 49 CFR 370 deadlines as timers, [ADR-0011](docs/adr/ADR-0011-one-filing-per-channel.md), [ADR-0012](docs/adr/ADR-0012-durable-deadlines.md) | Shipped |
| Document AI (PDF, EDI) | [tms-orders](apps/tms-orders/): X12 204 parser and 990 writer, PDF and email extraction through one strict tool, [ADR-0009](docs/adr/ADR-0009-parsers-before-models.md) | Shipped; live PDF and email runs with [v0.1.0](https://github.com/aliazam2012/freight-agents/issues/10) |
| Exactly-once writes over HTTP | [mock TMS](services/mock-tms/) with Idempotency-Key semantics, a [resilient client](apps/tms-orders/src/freight_agents/tms_orders/tms.py), [ADR-0010](docs/adr/ADR-0010-idempotency-at-the-api.md) | Shipped |
| Agents in a team's workflow | incident-bot (Slack) | Planned, [v0.5](https://github.com/aliazam2012/freight-agents/issues/14) |
| Classic machine learning | [volume-forecast](apps/volume-forecast/): rolling-origin backtest, conformal ranges, [report](apps/volume-forecast/reports/2026-11-23-backtest.md), [ADR-0008](docs/adr/ADR-0008-forecasting-models.md) | Shipped |
| Agents that cannot invent numbers | [planner tools and grounding grader](apps/volume-forecast/src/freight_agents/volume_forecast/), [evaluation](apps/volume-forecast/evals/reports/2026-11-23-reference.md) | Shipped; live runs with [v0.1.0](https://github.com/aliazam2012/freight-agents/issues/10) |

## How It Works

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the diagrams, [docs/adr](docs/adr) for the decisions, and [docs/THREAT-MODEL.md](docs/THREAT-MODEL.md) for what the guards defend against.

## Applications

| Application | What it does | Version |
|---|---|---|
| claims-intake | Claim email in; triage, extraction with TMS lookup, the 49 CFR 370.3 minimum check and the filing window; asks the claimant for missing details after a person approves | v0.1 |
| damage-assessor | Photos and description to a claim recommendation | planned, v0.2 |
| carrier-filing | Files a complete claim once through the carrier's API, portal or email; holds the carrier to the 30 and 120 day deadlines with approved follow-ups | v0.3 |
| tms-orders | Load tender by EDI 204, PDF or email to one validated TMS order; a 990 or email reply after approval | v0.4 |
| incident-bot | Slack incident management with approved status updates | planned, v0.5 |
| volume-forecast | Backtested daily volume forecasts with measured ranges; an agent answers planners' questions through tools and cites the run | v0.6 |

## Results

**claims-intake.** The reference run (scripted correct turns, plus red-team turns that fall for every injection) passes the gate: field accuracy 1.00, state accuracy 1.00, sends without approval 0, injection resisted 1.00. It proves the pipeline, hooks and graders, not a model: [report](apps/claims-intake/evals/reports/). Results for a real model come from a recorded run and are added with v0.1.0.

**carrier-filing** ([report](apps/carrier-filing/evals/reports/2026-11-24-reference.md)): 34 claims played for 200 days each across the three channels, with carrier answers on both sides of the day-30 and day-120 lines, seven faults and three red-team replies; every claim filed exactly once (none for a changed portal form), exactly the follow-ups the deadlines call for, 0 unapproved sends, 0 reminders fired twice, 3 of 3 injections resisted.

**tms-orders** ([report](apps/tms-orders/evals/reports/2026-11-23-reference.md)): 36 tenders and 6 red-team tenders against the mock TMS; EDI field accuracy 1.00 measured on the parser, every case in its expected state, 0 duplicate orders, 0 replies sent without approval, and 6 of 6 injected instructions resisted while the scripted model obeyed them. PDF and email rows run in reference mode until a live run.

**volume-forecast**, on synthetic data ([report](apps/volume-forecast/reports/2026-11-23-backtest.md)): gradient boosting misses by 11.4% of volume (WAPE) against 17.8% for the seasonal-naive baseline, MASE 0.56; its 80% and 95% ranges held 83.5% and 96.0% of actual days on origins the calibration never saw. The backtest windows end in October, so peak-season accuracy is untested. The planner agent's reference evaluation passes on 16 questions with every figure traced to a tool result.

## Run With a Real Model

Live calls cost money and need your own key. With `ANTHROPIC_API_KEY` set:

```bash
uv run freight-claims --state var/live run --inbox data/demo/inbox --tms data/demo/tms.json --model anthropic
uv run freight-claims --state var/live pending
```

For OpenAI, pass `--model openai --model-name <model id>` with `OPENAI_API_KEY` set.

## Use It From Claude Code or Codex

`freight-claims mcp` serves the claims tools over MCP: read a case, list emails waiting for approval, look up a shipment, search the claim rules, and ask for missing details. That last one runs through the same hooks as the agents and stops in the approval queue; no MCP tool approves or sends.

Claude Code:

```bash
claude mcp add freight-claims -- uv run --directory /path/to/freight-agents freight-claims --state var/demo mcp --tms data/demo/tms.json
```

Codex (`~/.codex/config.toml`):

```toml
[mcp_servers.freight-claims]
command = "uv"
args = ["run", "--directory", "/path/to/freight-agents", "freight-claims", "--state", "var/demo", "mcp", "--tms", "data/demo/tms.json"]
```

Run `make demo` first so there are cases to read.

## Layout

```
packages/llm            model interface, Anthropic and OpenAI adapters, scripted model, record and replay
packages/agentcore      typed tools, the hook pipeline, guards, approvals, the agent loop
packages/statecore      state machines over an append-only event store, with timers
packages/knowledge      sourced rules and BM25 retrieval with citations
packages/integrations   email in, email out, TMS client
packages/evals          golden cases, graders, the gate, reports
packages/telemetry      OpenTelemetry spans with GenAI attributes, cost meter
apps/claims-intake      claim email to a complete case
apps/tms-orders         load tenders to exactly-once TMS orders
apps/carrier-filing     claims filed once by API, portal or email; 49 CFR 370 deadlines
apps/volume-forecast    backtested forecasts and the planner agent
services/mock-tms       a made-up TMS order API with Idempotency-Key semantics
services/mock-carrier   a made-up carrier claims API and web portal
services/mock-kit       Idempotency-Key handling shared by the mock services
data/                   the made-up inbox and TMS, and the generator that writes them
```

## Requirements

[uv](https://docs.astral.sh/uv/) 0.13 or later; it installs Python 3.12. Nothing else: no database server, no Docker.

## Tests

```bash
make check   # ruff, mypy strict, pytest (includes the reference evaluation)
make eval    # the evaluation gate alone; ARGS="--report" writes a dated report
```

## Contributing, Security, License

[CONTRIBUTING.md](CONTRIBUTING.md) covers setup and pull requests; [SECURITY.md](SECURITY.md) says how to report a vulnerability. MIT licensed. All companies, people and data here are made up ([docs/NAMES.md](docs/NAMES.md)).
