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

## Residual Risk

- Taint matching is by value: an attacker address the model paraphrases or splits may not match. The recipient policy still limits mail to the claimant, so the remaining risk is content, not destination.
- The model can extract a wrong value (an amount, a date). Deterministic checks catch missing values, not wrong ones; the claim is filed later by a person or by carrier-filing with its own checks.
- Hidden HTML text reaches the model as ordinary text. It is tainted like the rest of the email.
- Attachment contents are not read in v0.1; damage-assessor (v0.2) adds images behind the same boundaries.
