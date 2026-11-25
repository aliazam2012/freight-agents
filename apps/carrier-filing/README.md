# carrier-filing

A complete freight claim, handed off by claims-intake, is filed with the carrier exactly once through that carrier's channel (a REST API, a web portal, or email), and the carrier is held to its 49 CFR 370.5 acknowledgement and 370.9 disposition deadlines with reminders that fire once and follow-ups a person approves.

## Table of Contents

- [Results](#results)
- [How It Works](#how-it-works)
- [Run It](#run-it)
- [Guards](#guards)
- [Limits](#limits)

---

## Results

From the [2026-11-24 evaluation](evals/reports/2026-11-24-reference.md): 34 claims, each played day by day for 200 days, across the three channels, with carriers answering on both sides of the day-30 and day-120 lines, seven faults and three red-team replies.

| Metric | Value |
|---|---|
| Claims filed exactly once (none for the changed portal form) | 1.00 |
| Exactly the follow-ups the 370 deadlines call for | 1.00 |
| Follow-ups citing their section | 1.00 |
| Claims ending in the right state | 1.00 |
| Sends without approval | 0 |
| Reminders fired twice | 0 |
| Red-team replies resisted | 3 of 3 |

Channels, timers and guards are real, including the portal in headless Chromium. Carrier replies are read in reference mode, so those rows check the guards, not a model.

## How It Works

| Part | Module | What it does |
|---|---|---|
| Packet | `domain.py`, `packet.py` | A handed-off claims-intake case becomes a packet for its carrier; a cover letter states the 49 CFR 370.3 elements; a packet missing one is never filed |
| Channels | `channels.py` | API: search, then write with an Idempotency-Key on the shared resilient HTTP layer. Portal: headless Chromium searches "my claims", fills the form, and counts a filing only with a confirmation number. Email: the approved message is the one sent, found again by its dated letter |
| Deadlines | `deadlines.py`, `machine.py` | Acknowledgement due 30 days and disposition 120 days after receipt, then status every 60 days; reminders at 09:00 claimant time on the first late day |
| Desk | `desk.py` | Files, fires reminders, drafts follow-ups that cite the rule, checks status, and reads carrier replies through one model tool |

[ADR-0011](../../docs/adr/ADR-0011-one-filing-per-channel.md) explains one filing per channel; [ADR-0012](../../docs/adr/ADR-0012-durable-deadlines.md) explains the deadlines.

## Run It

```bash
uv run freight-claims run --inbox data/demo/inbox --tms data/demo/tms.json    # claims-intake first
uv run freight-filing from-claims          # file every claim it handed off
uv run freight-filing pending              # claim emails and follow-ups waiting for a person
uv run freight-filing approve <approval-id> --by dana
uv run freight-filing tick                 # fire due 370 reminders (or --now 2027-01-02T16:00:00+00:00)
uv run freight-filing check <case-id>      # ask an API carrier for its status
uv run freight-filing eval                 # the 34 scenarios
uv run freight-filing mcp                  # read tools over MCP on stdio
```

The made-up carriers run in process: [mock-carrier](../../services/mock-carrier/) serves the API and, for the browser, the portal. The portal channel needs the headless browser once: `uv run playwright install --only-shell chromium`.

## Guards

| Attack or failure | What stops it |
|---|---|
| A crash after the carrier accepted the claim | Every channel searches before filing; the rerun finds the claim |
| A reply lost in flight | The API write carries an Idempotency-Key kept across retries |
| A portal session expires, or the form changes | The adapter raises before submit; nothing counts as filed without a confirmation number |
| A carrier reply asks to send documents elsewhere | The reply reader's only tool records what the reply says; follow-ups go only to the carrier's claims address |
| A reply from another address says the claim is paid | Replies count only from the carrier's claims address |
| A reminder after the carrier already answered | The timer is skipped because the case has moved on |

## Limits

- Carriers, claimants and the portal are made up; the portal login is a demo credential in the mock's source.
- Email filing cannot tell a delivered claim from a sent one; the 30-day reminder is the backstop.
- The model reads carrier replies in reference mode until a live run is recorded ([issue #10](https://github.com/aliazam2012/freight-agents/issues/10)).
