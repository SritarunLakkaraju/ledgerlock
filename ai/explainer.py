"""COMPONENT 4.1 -- Exception explainer (SS7.1). Strict I/O contract: the
model receives a structured exception (numbers only), returns a 1-2 sentence
explanation and one concrete action as JSON, and every numeral in its output
must already appear in its input -- P3, "AI narrates, never calculates."
Any violation (bad JSON, invented numerals, no API key, any API error)
falls back to a deterministic per-reason-code template built purely from
the exception's own fields, so the AI layer can never crash the run and can
never assert a number nobody gave it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

from engine.models import AIExplanation, Exception_
from engine.money import format_inr

SYSTEM_PROMPT = (
    "You are a finance-ops assistant. You receive a structured reconciliation "
    "exception. Explain it in 1-2 plain sentences for a finance controller and "
    "give one concrete next action. You must not compute, alter, round, or "
    "invent any number; only restate numbers given to you, formatted as ₹. "
    'Respond ONLY with JSON: {"explanation": str, "suggested_action": str}.'
)

MODEL = os.environ.get("LEDGERLOCK_AI_MODEL", "claude-sonnet-5")
_cache: dict[str, AIExplanation] = {}


def _digits(text: str) -> set[str]:
    return set(re.findall(r"\d+", text))


def _acceptable_input_number_groups(exc: Exception_) -> set[str]:
    """The system prompt asks the model to format money as ₹rupees.paise, so
    a correct restatement of a paise integer like 97640 legitimately renders
    as "976" and "40", neither of which is a literal substring of "97640".
    The guard's whitelist therefore includes each raw numeric field's digits
    AND its rupee/paise split -- but nothing else -- so a genuinely invented
    number still gets caught."""
    groups: set[str] = set()

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, bool):
            pass
        elif isinstance(v, int):
            n = abs(v)
            groups.add(str(n))
            rupees, paise = divmod(n, 100)
            groups.add(str(rupees))
            groups.add(f"{paise:02d}")
            groups.add(str(paise))
        elif isinstance(v, str):
            groups.update(re.findall(r"\d+", v))

    walk(exc.model_dump(exclude={"ai"}))
    return groups


def _numerals_ok(output_text: str, exc: Exception_) -> bool:
    output_groups = _digits(output_text)
    allowed = _acceptable_input_number_groups(exc)
    return output_groups.issubset(allowed)


def _code(exc: Exception_) -> str:
    return str(exc.reason_code.value if hasattr(exc.reason_code, "value") else exc.reason_code)


def _amt(exc: Exception_, side: str, key: str) -> str | None:
    d = exc.expected if side == "expected" else exc.actual
    v = d.get(key)
    return format_inr(v) if isinstance(v, (int, float)) else None


_TEMPLATES = {
    "ORPHAN_ORDER": lambda e: (
        f"Order {e.entities.get('order_id', '')} has no linked payment on record, so it cannot be reconciled.",
        "Check the payment gateway logs for a dropped or failed capture on this order.",
    ),
    "PAYMENT_NO_ORDER": lambda e: (
        f"Payment {e.entities.get('payment_id', '')} of {format_inr(e.amount_impact_paise)} doesn't map back to any order in the merchant system.",
        "Confirm whether this payment belongs to an order that failed to sync, then backfill the order record.",
    ),
    "AMOUNT_MISMATCH_ORDER_PAYMENT": lambda e: (
        f"Order {e.entities.get('order_id', '')} expected {_amt(e, 'expected', 'gross_amount_paise')}, but the linked payment shows {_amt(e, 'actual', 'gross_amount_paise')}, a difference of {format_inr(e.amount_impact_paise)}.",
        "Compare the order and payment records directly for a partial-capture or currency-rounding difference.",
    ),
    "FEE_MISMATCH": lambda e: (
        f"Payment {e.entities.get('payment_id', '')} was charged {_amt(e, 'actual', 'fee_paise')} in fees, but the configured rate implies {_amt(e, 'expected', 'fee_paise')} -- a {format_inr(e.amount_impact_paise)} gap.",
        "Check whether this payment's method or instant-settlement flag was recorded correctly before adjusting the fee.",
    ),
    "GST_MISMATCH": lambda e: (
        f"Payment {e.entities.get('payment_id', '')} shows GST of {_amt(e, 'actual', 'tax_paise')} against an expected {_amt(e, 'expected', 'tax_paise')}, a {format_inr(e.amount_impact_paise)} difference.",
        "Recompute GST as 18% of the recorded fee and confirm which figure is correct.",
    ),
    "UNLINKED_REFUND": lambda e: (
        f"Refund {e.entities.get('refund_id', '')} of {format_inr(e.amount_impact_paise)} doesn't reference a payment that exists in this dataset.",
        "Trace the refund to its parent payment in an earlier settlement export and re-link it.",
    ),
    "UNRECONCILED_ADJUSTMENT": lambda e: (
        f"Adjustment {e.entities.get('adjustment_id', '')} of {format_inr(e.amount_impact_paise)} has no parent payment reference, so its cause can't be verified automatically.",
        "Ask the settlements team for the source of this adjustment and attach the correct payment reference.",
    ),
    "SETTLEMENT_NET_MISMATCH": lambda e: (
        f"Settlement {e.entities.get('settlement_id', '')} was expected to net {_amt(e, 'expected', 'net_paise')} but the bank shows {_amt(e, 'actual', 'net_paise')}, a {format_inr(e.amount_impact_paise)} gap outside tolerance.",
        "Re-check every payment, refund, and adjustment line in this settlement for a missing or duplicated entry.",
    ),
    "DUPLICATE_UTR_UNRESOLVED": lambda e: (
        f"Settlement {e.entities.get('settlement_id', '')} shares its UTR with another settlement, and no candidate bank credit is close enough to its expected {_amt(e, 'expected', 'credit_paise')} to resolve automatically.",
        "Manually compare all bank credits under this UTR against each candidate settlement's expected net.",
    ),
    "MISSING_IN_BANK": lambda e: (
        f"Settlement {e.entities.get('settlement_id', '')} expected a bank credit of {_amt(e, 'expected', 'credit_paise')}, but none was found.",
        "Check with the bank for a delayed or on-hold settlement credit under this UTR.",
    ),
    "MISSING_IN_SETTLEMENT": lambda e: (
        f"A bank credit of {format_inr(e.amount_impact_paise)} under UTR {e.entities.get('utr', '')} doesn't match any settlement in the recon report.",
        "Check whether this credit belongs to a settlement that wasn't included in this recon export.",
    ),
    "TIMING_NOT_YET_SETTLED": lambda e: (
        f"Settlement {e.entities.get('settlement_id', '')} hasn't reached its expected settlement date yet.",
        "Re-run reconciliation for this settlement after its scheduled settlement date.",
    ),
}


def _template_fallback(exc: Exception_) -> AIExplanation:
    code = _code(exc)
    builder = _TEMPLATES.get(code)
    if builder:
        explanation, suggested_action = builder(exc)
    else:
        explanation = f"This {code} exception needs manual review; see the rule trace for details."
        suggested_action = "Review the source records referenced by this exception and resolve manually."
    return AIExplanation(explanation=explanation, suggested_action=suggested_action, model="template-fallback", cached=False)


def _cache_key(exc: Exception_) -> str:
    shape = {
        "reason_code": _code(exc),
        "expected": exc.expected,
        "actual": exc.actual,
        "amount_impact_paise": exc.amount_impact_paise,
        "entities": exc.entities,
    }
    h = hashlib.sha256(json.dumps(shape, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return f"{_code(exc)}:{h}"


def explain_exception(exc: Exception_) -> AIExplanation:
    key = _cache_key(exc)
    cached = _cache.get(key)
    if cached is not None:
        return AIExplanation(explanation=cached.explanation, suggested_action=cached.suggested_action, model=cached.model, cached=True)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        result = _template_fallback(exc)
        _cache[key] = result
        return result

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        payload = json.dumps(exc.model_dump(exclude={"ai"}), default=str)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": payload}],
        )
        text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
        parsed = json.loads(text)
        explanation = str(parsed["explanation"])
        suggested_action = str(parsed["suggested_action"])
        if not _numerals_ok(explanation + " " + suggested_action, exc):
            result = _template_fallback(exc)
        else:
            result = AIExplanation(explanation=explanation, suggested_action=suggested_action, model=MODEL, cached=False)
    except Exception:
        result = _template_fallback(exc)

    _cache[key] = result
    return result
