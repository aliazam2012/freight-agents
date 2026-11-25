# ADR-0012: The 370 deadlines as durable timers

Status: accepted 2026-11-24.

## Table of Contents

- [Context](#context)
- [Decision](#decision)
- [Consequences](#consequences)

---

## Context

49 CFR 370.5 gives a carrier 30 days from receipt to acknowledge a claim; 370.9 gives it 120 days to pay, decline or offer, and then requires a status letter every 60 days. A claimant who does not track these has nothing to hold the carrier to. The deadlines outlive any one process, and a reminder that fires twice, or fires after the carrier already answered, is noise a claims team learns to ignore.

## Decision

Deadlines are computed on dates from the day the carrier received the claim, never on clock time, so month ends and daylight-saving changes cannot move them. At filing the case schedules two timers on its own event log (statecore): the acknowledgement reminder and the disposition reminder, each at 09:00 claimant time on the first late day. A disposition follow-up schedules the next status reminder 60 days after the missed deadline, not after our letter, so the schedule cannot drift. A timer fires once; one that comes due after the case moved on (acknowledged on day 29, timer on day 31) is recorded as skipped. Every follow-up cites its section and waits for a person's approval.

## Consequences

The evaluation plays carrier answers on both sides of the day-30 and day-120 lines and checks that exactly the follow-ups the rules call for went out. The evaluation found one gap the unit tests had missed: a claim the carrier never acknowledged could not receive status reminders. It is fixed. Timers depend on something calling `tick`; in production that is a scheduler, here the CLI and the evaluation.
