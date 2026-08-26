"""COMPONENT 3 -- Metrics vs ground truth.

Joins engine output (ReconResult) to ground_truth.json on entity id and
scores it honestly. This module never adjusts engine behavior to hit a
target number -- it only measures what the engine actually produced.

Design decision (spec silent on exact join semantics -- see DECISIONS.md):
an entity_id is unique across the whole system (orders/payments/refunds/
adjustments/settlements/bank rows all use distinct id prefixes), so match
and exception records from every stage are merged into one per-entity
verdict: `is_match` is True only if the entity has at least one match record
and zero exception records anywhere in the run (an exception on an entity
always wins over a match on that same entity -- P5, honest by construction).
`reason_codes` is the union of every reason_code/tag touching that entity,
which is what `reason_code_accuracy` checks the expected code against.
"""
from __future__ import annotations

from collections import defaultdict

from engine.models import Exception_, MatchRecord, ReconResult

# Exception `entities` dicts carry contextual ids too (e.g. FEE_MISMATCH
# includes settlement_id for tracing) -- only the reason code's true SUBJECT
# should be marked "has_exception" for that entity. Scanning every key in
# `entities` would incorrectly flag e.g. a settlement whose net reconciled
# fine just because one of its payments had an unrelated fee mismatch.
REASON_PRIMARY_KEY = {
    "ORPHAN_ORDER": "order_id",
    "AMOUNT_MISMATCH_ORDER_PAYMENT": "order_id",
    "PAYMENT_NO_ORDER": "payment_id",
    "FEE_MISMATCH": "payment_id",
    "GST_MISMATCH": "payment_id",
    "UNLINKED_REFUND": "refund_id",
    "UNRECONCILED_ADJUSTMENT": "adjustment_id",
    "SETTLEMENT_NET_MISMATCH": "settlement_id",
    "DUPLICATE_UTR_UNRESOLVED": "settlement_id",
    "MISSING_IN_BANK": "settlement_id",
    "MISSING_IN_SETTLEMENT": "utr",
}


def _build_entity_verdicts(result: ReconResult) -> dict[str, dict]:
    verdicts: dict[str, dict] = defaultdict(lambda: {"reason_codes": set(), "has_match": False, "has_exception": False, "amount_impact_paise": 0})

    for m in result.matches:
        v = verdicts[m.entity_id]
        v["has_match"] = True
        v["reason_codes"].add(str(m.reason_code.value if hasattr(m.reason_code, "value") else m.reason_code))
        for t in m.tags:
            v["reason_codes"].add(str(t.value if hasattr(t, "value") else t))

    for e in result.exceptions:
        code = str(e.reason_code.value if hasattr(e.reason_code, "value") else e.reason_code)
        key = REASON_PRIMARY_KEY.get(code)
        val = e.entities.get(key) if key else None
        if val:
            _mark_exception(verdicts, val, e)

    return verdicts


def _mark_exception(verdicts: dict, entity_id: str, e: Exception_) -> None:
    v = verdicts[entity_id]
    v["has_exception"] = True
    v["reason_codes"].add(str(e.reason_code.value if hasattr(e.reason_code, "value") else e.reason_code))
    v["amount_impact_paise"] = e.amount_impact_paise


def compute_metrics(result: ReconResult, ground_truth_entities: list[dict], elapsed_seconds: float | None = None, total_records: int | None = None) -> dict:
    verdicts = _build_entity_verdicts(result)

    tp = fp = fn = tn = 0
    reason_flagged_total = 0
    reason_flagged_correct = 0
    matched_count = 0
    total_evaluated = 0

    for gt in ground_truth_entities:
        entity_id = gt["entity_id"]
        expected_code = gt["expected_reason_code"]
        is_reconcilable = gt["is_reconcilable"]
        v = verdicts.get(entity_id)
        if v is None and gt.get("true_bank_utr"):
            v = verdicts.get(gt["true_bank_utr"])
        if v is None:
            v = {"reason_codes": set(), "has_match": False, "has_exception": False}

        is_match = v["has_match"] and not v["has_exception"]
        total_evaluated += 1
        if is_match:
            matched_count += 1

        if is_reconcilable and is_match:
            tp += 1
        elif not is_reconcilable and is_match:
            fp += 1
        elif is_reconcilable and not is_match:
            fn += 1
        else:
            tn += 1

        if expected_code != "AUTO_MATCHED":
            reason_flagged_total += 1
            if expected_code in v["reason_codes"]:
                reason_flagged_correct += 1

    auto_match_rate = matched_count / total_evaluated if total_evaluated else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    reason_code_accuracy = reason_flagged_correct / reason_flagged_total if reason_flagged_total else 1.0

    exceptions_by_reason: dict[str, dict] = defaultdict(lambda: {"count": 0, "amount_impact_paise": 0})
    for e in result.exceptions:
        code = str(e.reason_code.value if hasattr(e.reason_code, "value") else e.reason_code)
        exceptions_by_reason[code]["count"] += 1
        exceptions_by_reason[code]["amount_impact_paise"] += e.amount_impact_paise

    rounding_drift_matches = [m for m in result.matches if str(m.reason_code.value if hasattr(m.reason_code, "value") else m.reason_code) == "ROUNDING_DRIFT_ABSORBED"]
    rounding_drift_total_paise = sum(abs(m.details.get("drift_paise", 0)) for m in rounding_drift_matches)

    value_flagged_paise = sum(e.amount_impact_paise for e in result.exceptions)
    stage_c_settled_reasons = {"AUTO_MATCHED", "ROUNDING_DRIFT_ABSORBED", "DUPLICATE_UTR_RESOLVED", "FUZZY_NARRATION_MATCH"}
    value_reconciled_paise = sum(
        m.details.get("bank_credit_paise", 0)
        for m in result.matches
        if m.stage == "C" and str(m.reason_code.value if hasattr(m.reason_code, "value") else m.reason_code) in stage_c_settled_reasons
    )

    throughput = (total_records / elapsed_seconds) if (elapsed_seconds and total_records) else None

    return {
        "auto_match_rate": round(auto_match_rate, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_match_count": fp,
        "true_positive_count": tp,
        "false_negative_count": fn,
        "true_negative_count": tn,
        "total_entities_evaluated": total_evaluated,
        "matched_count": matched_count,
        "exceptions_by_reason": dict(exceptions_by_reason),
        "value_reconciled_paise": value_reconciled_paise,
        "value_flagged_paise": value_flagged_paise,
        "rounding_drift_absorbed": {"count": len(rounding_drift_matches), "total_paise": rounding_drift_total_paise},
        "reason_code_accuracy": round(reason_code_accuracy, 4),
        "throughput_records_per_sec": round(throughput, 1) if throughput is not None else None,
    }
