# Threat Model

## Table of Contents

- [Assets](#assets)
- [Trust Boundaries](#trust-boundaries)
- [Threats and Controls](#threats-and-controls)
- [Residual Risk](#residual-risk)

---

## Assets

Claim cases and their history, the claimant's contact details, outbound email in the company's name, model spend, and the shipment data in the TMS.

## Trust Boundaries

Everything in an email (sender, subject, body, attachment names and contents) is untrusted. Model output is untrusted: it is a proposal that hooks and the state engine check. The TMS and the operator's configuration are trusted. A person approving a send is trusted for that one message.

## Threats and Controls

| Threat | Control | Where |
|---|---|---|
| Prompt injection steers a send to an attacker | Every email value is tainted; a tainted recipient is refused unless it is the claimant; any recipient other than the claimant is refused | taint_guard, recipient_policy |
| Injection text closes the document block | The email is HTML-escaped inside its block | render_email |
| A send goes out without review | SEND tools wait for an approval of the exact call, used once | approval_gate, ApprovalQueue |
| A retried step files or saves twice | Writes are keyed by tool, case and arguments; a repeat returns the first result | idempotency |
| The model skips a step or jumps state | Tools are allowed only in listed states; transitions are guarded in code | state_allowlist, StateMachine |
| Runaway cost or loops | Limits on turns, tool calls and dollars per run | Budget, budget_guard |
| Personal data in logs or model context | Phone and card numbers masked in tool outputs | redact_pii |
| Tampering with history | Events table refuses UPDATE and DELETE | SqliteEventStore triggers |
| Secrets in the repository | Keys only from the environment; secret scanning in CI | gitleaks (v0.1 CI) |
| Vulnerable dependencies | One lockfile; dependency audit and Dependabot | pip-audit, Dependabot |
| Text in a tender redirects a load (tms-orders) | Stops must be in the shipper's location master; a new location waits for a person | validate_order, address.unknown_location |
| A tender's text names another reply address | Replies go only to the tender's sender (the email From or the shipper's directory entry), and wait for approval | recipient_policy, taint_guard, approval_gate |
| A fake cancellation or change in a tender | A change or cancellation needs an existing order for the same load; otherwise a person decides | submit, needs_review |
| The order changes between validation and the TMS write | The write must match the validated order exactly | matches_validated |
| A lost reply or retry creates a second order | Writes carry an Idempotency-Key kept across retries; the TMS replays the first answer; the load's fingerprint is searched before any write | HttpTms, mock TMS, submit |
| A broken or hostile EDI file | Envelope counts and control numbers are checked; values holding a separator are refused on write | x12.parse_interchange, write_204 |
| A carrier reply asks to send documents or money elsewhere (carrier-filing) | The model reading replies has one tool, to record what the reply says; follow-ups go only to the carrier's claims address, after approval | read_reply, recipient_policy, approval_gate |
| A reply from another address claims the claim is paid | A reply counts only from the carrier's claims address; any other is noted as unverified and changes nothing | read_reply |
| A claim is filed twice after a crash or a lost reply | Each channel searches before filing; the API also writes with an Idempotency-Key; a portal filing counts only with a confirmation number | ApiChannel, PortalChannel, EmailChannel |
| Portal automation submits a half-filled form | A missing field or an expired session raises before submit; nothing counts as filed without a confirmation number | PortalChannel |
| Text in an incident channel asks the bot to post elsewhere or tell customers something (incident-bot) | Channel messages only enter the timeline; the model drafts through record-only tools; code posts without approval only in the incident's own channel; customer updates and outside posts wait for approval | IncidentDesk, channel_policy, approval_gate |
| Text claims a severity change or an approval | Only slash commands change an incident; approvals are a person's action on the desk | IncidentDesk |
| A postmortem names a person | Prose sections replace Slack mentions and user ids with "a responder" before publishing | blameless |
| Slack redelivers an event | Event ids are handled once, and a message already in the timeline is not recorded again | SeenEvents, IncidentDesk.message |

## Residual Risk

- Taint matching is by value: an attacker address the model paraphrases or splits may not match. The recipient policy still limits mail to the claimant, so the remaining risk is content, not destination.
- The model can extract a wrong value (an amount, a date). Deterministic checks catch missing values, not wrong ones; the claim is filed later by a person or by carrier-filing with its own checks.
- Hidden HTML text reaches the model as ordinary text. It is tainted like the rest of the email.
- Attachment contents are not read in v0.1; damage-assessor (v0.2) adds images behind the same boundaries.
- tms-orders: a model fooled into choosing a wrong value that the document also states and the rules allow (an injected lower weight, a second date) gets through validation. Code checks that values are present, plausible and unchanged after validation; it cannot tell which of two stated values the shipper meant. EDI tenders do not pass through the model, so the gap covers PDF and email only.
- carrier-filing: a portal sign-in for the made-up carrier lives in the mock's source; a real deployment would take carrier credentials from a secret store, which this repository does not model.
