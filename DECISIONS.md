# Decisions

Places the build prompt (`reconciler-build-prompt-v2.md`) left silent, and what was chosen instead. Per the prompt's own instruction: "Where this spec is silent, choose the simplest correct option and note it here."

## Engine

**Settlement "actual net" (SS5.3's `s.net`) comes from the bank statement, not the recon report.**
The pseudocode compares `expected` (recomputed from `razorpay_recon.csv` rows) against `s.net` inside the same per-settlement loop. If `s.net` were *also* derived purely from the recon rows, the comparison would be tautological -- both sides would always agree, and `SETTLEMENT_NET_MISMATCH` / `ROUNDING_DRIFT_ABSORBED` could never fire. Instead: `expected_net_paise` is computed entirely from recon rows (Σ payment net − Σ refund debit − Σ linked-adjustment debit), and Stage B compares it against the settlement's bank credit *only* when the UTR resolves to exactly one unambiguous bank row. When it's ambiguous (0 or >1 candidates, or `on_hold`), Stage B skips the diff check for that settlement and defers entirely to Stage C, which owns bank identification. This keeps one root cause (e.g. a duplicate UTR) from producing two conflicting exceptions across stages B and C.

**An unreconciled adjustment doesn't cascade into a settlement-level net mismatch.**
The pseudocode's adjustment branch only subtracts `t.debit` from `expected` when `parent_payment_id` is present -- an unlinked adjustment's amount is *never* netted into `expected`. If the settlement's true bank-credited amount included that adjustment's effect anyway, the settlement would *also* fail its net check purely as a side effect of one stray line item, muddying a clean, isolated exception into two. Decision: the settlement's actual net always equals its computed net (never nets out an unlinked adjustment either), so only the adjustment entity itself is flagged `UNRECONCILED_ADJUSTMENT`; the settlement still matches cleanly.

**Stage C resolves duplicate UTRs by grouping settlements upfront, not by processing them one-by-one against a shrinking claimed-set.**
A naive per-settlement loop (as the pseudocode's `for s in settlements` reads literally) means: when two settlements share a UTR, the *first* one processed sees 2 candidates and correctly gets tagged `DUPLICATE_UTR_RESOLVED`, but by the time the *second* one is processed, one candidate is already claimed -- it sees only 1 remaining candidate, takes the "clean single match" path, and reads as a plain `AUTO_MATCHED`. Same money, correctly resolved, but the tag silently disappears for one side of the pair. Stage C instead groups settlements by `settlement_utr` first; any UTR shared by >1 settlement (or matched to >1 bank row) is resolved as a group, with every member tagged consistently via the same deterministic argmin tie-break (amount diff, then date diff, then `bank_ref_no`).

**`TIMING_NOT_YET_SETTLED` is a reserved reason code, not an implemented check.** It's in the fixed enum (SS5.5) but no rule in SS5.2-5.4 ever produces it, and it implies an "as-of" cutoff date concept this build doesn't have (all generated data is historical). Left unimplemented rather than inventing an unspecified trigger condition.

## Metrics

**Entity verdicts merge match + exception records across all three stages, keyed by entity id; an exception on an entity always wins over a match on that same entity.** Order/payment/refund/adjustment/settlement/bank-row ids are unique across the whole system by construction (distinct prefixes), so this is a safe global join. `reason_code_accuracy` checks the ground truth's `expected_reason_code` against the *union* of every reason code and tag touching that entity, not just one record -- this is what lets a settlement carry both `ROUNDING_DRIFT_ABSORBED` and `MULTI_DAY_SETTLEMENT_OK` simultaneously and still score correctly against either expectation.

**Exception `entities` dicts carry contextual ids as well as the true subject** (e.g. `FEE_MISMATCH` includes `settlement_id` purely for tracing). Metrics uses an explicit reason-code -> primary-subject-key mapping rather than scanning every key, so a payment-level fee mismatch doesn't incorrectly flag its parent settlement as unmatched when the settlement's own net reconciled fine.

## Generator

**Anomaly sampling floors to at least 1 occurrence whenever `rate > 0` and the eligible pool is non-empty**, via `max(1, round(rate * population))` instead of plain rounding. With `n_orders=300` over a 14-day, 2-day-cycle window, the settlement population is small (~10-15 before merging); plain rounding floors every low-rate settlement-level anomaly (`duplicate_utr`, `missing_in_bank`, `missing_in_settlement`, `adjustment`: all ≤0.02) to zero, which would silently violate "≥8 anomaly types each caught" in the definition of done. This trades exact adherence to the configured *rate* for guaranteed *coverage* -- reasonable for a fixed-size demo dataset where the whole point is showing every anomaly type work correctly at least once.

**`INSTANT_SETTLEMENT_RATE = 0.15`** is a generator-only constant (not in `config.yaml`) controlling what fraction of settlements are flagged `is_instant` before `fee_variance_instant` samples among them. The spec's fee-rate table needs *some* settlements to be instant for that anomaly type to have anything to act on, but never specifies the base instant rate itself.

**Ground truth records at most one "primary" injected anomaly per settlement** among `{rounding_drift, duplicate_utr, missing_in_bank, fee_variance_instant, adjustment-host}` (mutually exclusive by construction), plus `multi_day_settlement` as a fallback label only when no other primary anomaly applies. The engine still tags `MULTI_DAY_SETTLEMENT_OK` on *every* structurally multi-day settlement regardless of what else is going on with it -- ground truth just picks one label per entity to keep `test_anomalies.py` and `reason_code_accuracy` well-defined per entity.

## AI layer

**The numeral guard's whitelist includes each numeric field's raw digits *and* its rupee/paise split**, not just the raw paise integer. The system prompt asks the model to format money as `₹rupees.paise`; a legitimate restatement of `97640` paise as "₹976.40" naturally splits into digit-groups "976" and "40", neither of which is a literal substring of "97640". A naive "output digits ⊆ input digits (as one big substring)" check would reject *every* correctly-formatted currency restatement. The whitelist is still exact per number (only that field's own rupees/paise components are allowed), so a genuinely invented figure is still caught.

**The fuzzy narration matcher (SS7.2) is deterministic only.** The optional LLM-assisted pass for the ambiguous 0.5-0.85 score band is explicitly called a stretch in the spec and isn't implemented; scores in that band fall through to `MISSING_IN_BANK` rather than auto-accepting.

**The Q&A agent (SS7.3) is not implemented.** Explicitly marked stretch in the spec; `POST /runs/{run_id}/ask` returns `501`.

## API / infra

**Run state lives in an in-memory dict, not SQLite.** The spec allows either; a buildathon demo process doesn't need state to survive a restart, and every `/generate` call is meant to start a fresh run anyway.

**The frontend's "locking" stage animation (SS9) is client-side simulated timing, not real backend staging.** `/reconcile` is one atomic call -- the engine doesn't stream stage-by-stage progress. The UI advances an A -> B -> C indicator on fixed delays while the request is in flight, then snaps to the real result the moment the response lands (never earlier), so the animation always reflects reality's *outcome*, just not real-time progress.
