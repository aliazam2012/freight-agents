# Runbook: Demo

## Table of Contents

- [Run the Demo](#run-the-demo)
- [Review and Approve](#review-and-approve)
- [Start Over](#start-over)

---

## Run the Demo

```bash
make setup
make demo
```

`make demo` regenerates the made-up inbox and TMS (`make data`), then processes all 36 emails into `var/demo/` with scripted reference turns: 14 claims end ready to file, 14 need information (8 ordinary, 6 attacks whose sends were refused), 8 are not claims.

## Review and Approve

```bash
uv run freight-claims --state var/demo pending
uv run freight-claims --state var/demo approve <approval id> --by <your name> --tms data/demo/tms.json
uv run freight-claims --state var/demo show <case id>
```

Approving writes the email to `var/demo/outbox/` and moves the case to `awaiting_reply` with a 7-day reminder.

## Start Over

`make demo` deletes `var/demo/` before it runs, so every run starts clean.
