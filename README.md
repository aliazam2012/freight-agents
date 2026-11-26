# freight-agents (moved)

On 2026-11-25 this repository split into seven, each named for what it does, each with its own history, CI and evaluation gate. This one is archived; every folder below now lives in its new home.

| Was here | Now | What it shows |
|---|---|---|
| `packages/`, `services/mock-kit`, `tools/`, shared docs and ADR-0001 to 0007 and 0010 | [agent-runtime](https://github.com/aliazam2012/agent-runtime) | Guarded tools, state machines with timers, human approval, evaluation gates, record and replay, MCP |
| `apps/claims-intake`, `data/demo` | [claims-intake-agent](https://github.com/aliazam2012/claims-intake-agent) | Extraction from email, federal claim rules with citations, prompt-injection defense |
| `apps/damage-assessor`, `data/damage`, ADR-0014 | [vision-damage-assessor](https://github.com/aliazam2012/vision-damage-assessor) | Vision AI: the model describes, code decides, calibrated confidence |
| `apps/carrier-filing`, `services/mock-carrier`, ADR-0011, 0012 | [carrier-claims-filing](https://github.com/aliazam2012/carrier-claims-filing) | REST API, headless browser and email integrations, durable legal deadlines |
| `apps/tms-orders`, `services/mock-tms`, `data/tenders`, ADR-0009 | [edi-pdf-order-intake](https://github.com/aliazam2012/edi-pdf-order-intake) | Document AI: EDI X12 parsing, PDF and email extraction, exactly-once writes |
| `apps/incident-bot`, the postmortem template, ADR-0013 | [slack-incident-bot](https://github.com/aliazam2012/slack-incident-bot) | An agent in a team's workflow: Slack, cadence reminders, cited runbooks, approved updates |
| `apps/volume-forecast`, ADR-0008 | [freight-volume-forecast](https://github.com/aliazam2012/freight-volume-forecast) | Classic machine learning, backtesting, an agent that cannot invent numbers |

Open issues moved with their code: the recorded real-model run to agent-runtime, damage-assessor's calibration to vision-damage-assessor. The full history of this monorepo stays here, read-only.
