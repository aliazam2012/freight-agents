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
- [How It Works](#how-it-works)
- [Applications](#applications)
- [Results](#results)
- [Run With a Real Model](#run-with-a-real-model)
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

## How It Works

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the diagrams, [docs/adr](docs/adr) for the decisions, and [docs/THREAT-MODEL.md](docs/THREAT-MODEL.md) for what the guards defend against.

## Applications

| Application | What it does | Version |
|---|---|---|
| claims-intake | Claim email in; triage, extraction with TMS lookup, the 49 CFR 370.3 minimum check and the filing window; asks the claimant for missing details after a person approves | v0.1 |
| damage-assessor | Photos and description to a claim recommendation | planned, v0.2 |
| carrier-filing | Files a complete claim through the carrier's API, portal or email; tracks the 30 and 120 day timers | planned, v0.3 |
| tms-orders | Load tender by email, PDF or EDI 204 to a validated TMS order | planned, v0.4 |
| incident-bot | Slack incident management with approved status updates | planned, v0.5 |
| volume-forecast | Backtested volume forecasts with an agent that answers planners' questions | planned, v0.6 |

## Results

The reference run (scripted correct turns, plus red-team turns that fall for every injection) passes the gate: field accuracy 1.00, state accuracy 1.00, sends without approval 0, injection resisted 1.00. It proves the pipeline, hooks and graders, not a model: [report](apps/claims-intake/evals/reports/). Results for a real model come from a recorded run and are added with v0.1.0.

## Run With a Real Model

Live calls cost money and need your own key. With `ANTHROPIC_API_KEY` set:

```bash
uv run freight-claims --state var/live run --inbox data/demo/inbox --tms data/demo/tms.json --model anthropic
uv run freight-claims --state var/live pending
```

For OpenAI, pass `--model openai --model-name <model id>` with `OPENAI_API_KEY` set.

## Layout

```
packages/llm            model interface, Anthropic and OpenAI adapters, scripted model, record and replay
packages/agentcore      typed tools, the hook pipeline, guards, approvals, the agent loop
packages/statecore      state machines over an append-only event store, with timers
packages/knowledge      sourced rules and BM25 retrieval with citations
packages/integrations   email in, email out, TMS client
packages/evals          golden cases, graders, the gate, reports
packages/telemetry      OpenTelemetry spans with GenAI attributes, cost meter
apps/claims-intake      the first application
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
