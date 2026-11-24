# tms-orders

A load tender that arrives as an X12 EDI 204, a PDF rate confirmation or a plain email becomes one validated order in a TMS, exactly once, and the shipper gets a confirmation (a 990 for EDI, an email otherwise) or a decline with its reasons, after a person approves the reply.

## Table of Contents

- [Results](#results)
- [How It Works](#how-it-works)
- [Run It](#run-it)
- [Guards](#guards)
- [Sources](#sources)
- [Limits](#limits)

---

## Results

From the [2026-11-23 evaluation](evals/reports/2026-11-23-reference.md), 36 tenders (12 per input type) and 6 red-team tenders, against the mock TMS:

| Metric | Value |
|---|---|
| EDI field accuracy (parser, real measurement) | 1.00 |
| PDF and email field accuracy (reference mode) | 1.00 |
| Cases stopping in the right state | 1.00 |
| Duplicate orders in the TMS | 0 |
| Replies sent without approval | 0 |
| Red-team attacks resisted (the model obeys each one) | 6 of 6 |

The 36 tenders include a resend of an earlier tender under a new reference, a change, a cancellation, an overweight load and a hazmat or appointment-window break for each input type; 21 valid originals make 21 orders, and every resend maps to its existing order. PDF and email run in reference mode, so their rows check the pipeline and the guards, not a model. A live model's numbers come with the first recorded run ([issue #10](https://github.com/aliazam2012/freight-agents/issues/10)).

## How It Works

| Step | Module | What happens |
|---|---|---|
| Read | `workflow.read_document` | EDI is parsed by code (`edi204.py` on the shared X12 envelope reader); PDF text comes from pypdf; email from the .eml |
| Extract | `extract.py` | For PDF and email only, the model reads the escaped document and calls its one tool, `record_order`; anything the document does not state stays null and sends the case to a person |
| Validate | `validate.py` | Sourced rules: USPS state and ZIP formats, stop order, appointment windows compared in UTC from each stop's zone, transit time, trailer payloads, reefer setpoints, hazmat shipping-paper elements, emergency phone, placards; and the location master |
| Submit | `submit.py`, `tms.py` | The TMS is searched by the load's fingerprint, then written with an Idempotency-Key kept across retries; a change or cancellation with no order goes to a person |
| Reply | `workflow.py`, `edi204.write_990` | A 990 (accept A, decline D) or an email, drafted by code and held for approval |

Every case is a state machine (`machine.py`): received, parsed, validated, submitted, confirmation pending, confirmed, with needs review, declining, decline pending, declined and duplicate. Running the same file again resumes the case where it stopped, so a crash or a TMS outage never repeats a step. [ADR-0009](../../docs/adr/ADR-0009-parsers-before-models.md) explains why only free text reaches the model; [ADR-0010](../../docs/adr/ADR-0010-idempotency-at-the-api.md) explains exactly-once orders.

## Run It

```bash
make data                                  # or: uv run python data/generate_tenders.py
uv run freight-orders run                  # every tender in data/tenders, against the in-process mock TMS
uv run freight-orders pending              # replies waiting for a person
uv run freight-orders approve <approval-id> --by dana
uv run freight-orders review <case-id> submit --by dana    # or decline
uv run freight-orders show <case-id>
uv run freight-orders eval                 # the golden and red-team sets
uv run freight-orders mcp                  # read-only tools over MCP on stdio
```

`--tms-url` points at a running TMS instead of the in-process [mock](../../services/mock-tms/). `run --model anthropic` (with `ANTHROPIC_API_KEY`) or `--model openai --model-name <id>` reads PDF and email with a live model; live calls cost money.

## Guards

| Attack or failure | What stops it |
|---|---|
| Tender text redirects a delivery | Stops must be in the shipper's location master; a new location waits for a person |
| Tender text names another reply address | Replies go only to the sender, through the recipient policy and the taint guard, after approval |
| Tender text fakes a cancellation | A cancellation needs an existing order for the load; otherwise a person decides |
| The order changes after validation | The TMS write must match the validated order exactly |
| A reply lost after the TMS saved the order | The retry carries the same Idempotency-Key and the TMS replays the first answer |
| The TMS is down or rate limiting | Circuit breaker, retry budget and backoff; the case waits in validated and a rerun finishes it |
| The model calls a tool it does not have | The extraction agent's registry holds only `record_order`; the red-team set tries it |

## Sources

The rules are summarized, with links and read dates, in the knowledge package's [order rules](../../packages/knowledge/src/freight_agents/knowledge/docs/orders/), which the MCP server can search: the CN and C.H. Robinson X12 204 guides and C.H. Robinson's 990 specification, 49 CFR 172.202, 172.504 and 172.604, 23 U.S.C. 127, C.H. Robinson's trailer equipment guide, USPS Publication 28, and the IETF Idempotency-Key draft. Where the partner guides are silent, this made-up partner's conventions are written in `edi204.py` and never presented as X12 facts. Planning assumptions (road miles, miles per day, the location master) are labeled as such in each finding.

## Limits

- Tenders, companies and places are made up; the network serves 12 cities.
- A model fooled into choosing a wrong value the document also states and the rules allow gets through validation; see the [threat model](../../docs/THREAT-MODEL.md).
- Placard checks judge Table 1 by hazard class alone and use the order weight for the hazmat weight.
- Scanned PDFs have no text layer and go to a person; there is no OCR.
