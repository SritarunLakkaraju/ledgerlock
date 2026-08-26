# LedgerLock

**AI Three-Way Settlement Reconciler** -- built for the Razorpay Buildathon (Track 04, AI Finance Controller).

LedgerLock ingests three files a merchant actually has -- their own **orders**, Razorpay's **settlement recon report**, and their **bank statement** -- and reconciles them three ways: order ↔ payment, payment ↔ settlement (fees, GST, refunds, adjustments), settlement ↔ bank credit (by UTR). It reports an **honest auto-match rate measured against generated ground truth**, a **zero-tolerance false-match count**, and an **exception list** where every unresolved record carries a fixed reason code, an evidence trace, and a plain-English explanation an LLM is only ever allowed to *narrate*, never compute.

```
$ make demo

LedgerLock -- seed 42
  300 orders, 12 settlements, 12 bank rows
  96.7% auto-matched · 12 flagged · 0 false matches
  ₹3,46,817.58 reconciled / ₹11,969.39 flagged
  reason-code accuracy: 100.0%
```

## Problem

Reconciling payments against Razorpay settlements against bank credits is currently a manual, spreadsheet-driven process for most merchants -- three files, three different keys (order id, payment id, UTR), fees and GST netted in at Razorpay's end, refunds that land in a *different* settlement than the payment they refund. The bottleneck isn't running the numbers once; it's *verifying* them, over and over, every settlement cycle, and trusting the result enough to close the books.

## Why a deterministic core + AI narration

The matching engine (`engine/`) is plain Python: pydantic models, arithmetic in integer paise, explicit rule tables. Given the same three inputs, it produces byte-identical output every time -- no model call, no sampling, no variance in the numbers a finance controller has to sign off on. That determinism is the whole point: `auto_match_rate`, `false_match_count`, and `reason_code_accuracy` are things a skeptical judge can re-run themselves with `--seed 42` and get the *exact* numbers printed above.

An LLM only enters the picture after every number has already been computed. `ai/explainer.py` receives a fully-resolved exception object and is contractually restricted to *narrating* it: one to two plain-English sentences and one suggested action, returned as strict JSON, with a hard post-validation guard that extracts every numeral from its output and rejects the response (falling back to a deterministic template) if any numeral doesn't already appear in its input. The model can misexplain a number. It cannot invent one that reaches a screen.

See [`DECISIONS.md`](DECISIONS.md) for every place the spec was silent and what was chosen instead.

## Tolerance policy

```
tolerance: abs_paise=100, rel=0.001   # <= Rs1.00 or <= 0.1% of the expected amount, whichever is SMALLER
```

A difference is "within tolerance" if `diff <= min(tolerance.abs_paise, round(tolerance.rel * expected))`. For a typical settlement (tens of thousands of paise), the relative cap usually binds and is tighter than a flat Rs1; for very small amounts (a single payment's fee/GST), the relative cap often rounds to 0, meaning fee and GST math has effectively **zero** tolerance -- any real deviation is flagged, by design. The `rounding_drift` anomaly exists specifically to exercise the *settlement-level* tolerance band; individual fee/GST checks are meant to be exact.

## How metrics are measured against ground truth

The generator (`generator/generate.py`) writes `ground_truth.json` alongside the three source files, labeling every entity (order, payment, refund, adjustment, settlement, stray bank row) with `is_reconcilable` and an `expected_reason_code`. **The engine never reads this file.** Only `metrics/compute.py` does, in a separate pass after reconciliation, joining the engine's matches and exceptions back to ground truth by entity id:

- `auto_match_rate` -- fraction of all ground-truth entities the engine matched cleanly (no exception anywhere).
- `precision` / `recall` / `f1` -- positive class = "ground truth says reconcilable, and the engine matched it."
- `false_match_count` -- ground truth says *not* reconcilable, but the engine matched it anyway. **Must be 0.**
- `reason_code_accuracy` -- for every entity ground truth expects a non-`AUTO_MATCHED` reason code, did the engine assign that exact code (as a match tag or an exception)?

This is what makes a 96.7% number trustworthy instead of self-reported: it's not "96.7% of things I decided to call matched," it's "96.7% of the entities the generator knows the true answer for, and I can prove it with `reason_code_accuracy: 100%`."

## Reproduce our exact numbers

```bash
make install      # creates .venv, installs Python deps
make test          # 51 tests: money math, all three stages per reason code,
                    # all 11 anomaly types, the golden seed-42 run, the AI numeral guard
make demo SEED=42  # generate -> reconcile -> print headline numbers -> serve API + UI
```

`make demo` (or `python -m generator.generate --seed 42` directly) is fully deterministic: same seed, byte-identical `orders.csv` / `razorpay_recon.csv` / `bank_statement.csv` / `ground_truth.json`, and the exact metrics shown at the top of this README. `tests/test_golden.py` pins those numbers as a regression test.

Once `make demo` is running: API on `http://127.0.0.1:8000` (docs at `/docs`), UI on `http://localhost:5173`.

## Anomaly catalogue

11 anomaly types, each injected by the generator with a ground-truth label and each caught by the engine with a specific reason code (`tests/test_anomalies.py` asserts every one, end to end, off the real generator output):

| Anomaly | Reason code | Reconcilable? |
|---|---|---|
| `orphan_order` | `ORPHAN_ORDER` | No |
| `partial_refund_same_settlement` | `AUTO_MATCHED` | Yes |
| `partial_refund_later_settlement` | `REFUND_IN_LATER_SETTLEMENT_OK` | Yes |
| `full_refund_later_settlement` | `REFUND_IN_LATER_SETTLEMENT_OK` | Yes |
| `multi_day_settlement` | `MULTI_DAY_SETTLEMENT_OK` | Yes |
| `rounding_drift` | `ROUNDING_DRIFT_ABSORBED` | Yes |
| `duplicate_utr` | `DUPLICATE_UTR_RESOLVED` | Yes |
| `missing_in_bank` | `MISSING_IN_BANK` | No |
| `missing_in_settlement` | `MISSING_IN_SETTLEMENT` | No |
| `adjustment` (unlinked) | `UNRECONCILED_ADJUSTMENT` | No |
| `fee_variance_instant` | `FEE_VARIANCE_INSTANT_OK` | Yes |

Six of these are genuinely fine (a match with an explanatory tag); five are real exceptions. That split is the point: most of what looks like a discrepancy at first glance -- a refund landing two settlements later, a rounding difference of a few paise, an instant-settlement fee premium -- has a legitimate explanation and shouldn't block reconciliation. What's left after explaining those away is a short, honest, correctly-labeled list of things that actually need a human.

## Repository layout

```
config.yaml           seed, fee rates, tolerance policy, anomaly rates
generator/             COMPONENT 1 -- synthetic data + ground truth
engine/                COMPONENT 2 -- money math, models, Stage A/B/C
metrics/               COMPONENT 3 -- scoring vs ground truth
ai/                    COMPONENT 4 -- exception explainer + fuzzy narration matcher
api/                   COMPONENT 5 -- FastAPI
ui/                    COMPONENT 6 -- React + Vite + Tailwind
tests/                 COMPONENT 7 -- the credibility layer (51 tests)
DECISIONS.md           every spec-silent choice, and why
```

## Anti-goals (from the spec, still true)

No LLM arithmetic. No floats for money. No 100% demo. No unexplained match. No demo hard-wired to one lucky seed. No real financial data or PII. No random tie-breaks.
