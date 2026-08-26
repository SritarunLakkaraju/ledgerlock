"""COMPONENT 2 -- Reconciliation engine. Pure Python/pydantic, no I/O inside
the matching functions: callers pass in normalized records, get results back.

Design decision (spec silent on where Stage B's "s.net" comes from -- see
DECISIONS.md): a settlement's `expected_net_paise` is computed entirely from
razorpay_recon.csv rows (Sigma payment net - Sigma refund debit - Sigma
linked-adjustment debit). Stage B compares that against the settlement's bank
credit ONLY when the UTR resolves to exactly one unambiguous bank row (the
common case); when it's ambiguous (0 or >1 candidates, or on_hold) Stage B
skips the diff check for that settlement and defers entirely to Stage C,
which owns bank identification (duplicates, missing rows, fuzzy fallback).
This keeps one root cause from producing two conflicting exceptions.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from ai.fuzzy import fuzzy_score
from engine.models import BankTxn, EntityType, Exception_, MatchRecord, Order, ReconResult, ReconTxn
from engine.money import calc_fee_paise, calc_gst_paise, calc_net_paise, effective_fee_rate, within_tolerance

FUZZY_ACCEPT_THRESHOLD = 0.85
FALLBACK_WINDOW_DAYS = 3


@dataclass
class SettlementMeta:
    settlement_id: str
    settlement_utr: str
    settled_at: object
    on_hold: bool
    is_instant: bool
    txns: list[ReconTxn] = field(default_factory=list)
    expected_net_paise: int = 0


@dataclass
class NormalizedData:
    orders: list[Order]
    payments_by_id: dict[str, ReconTxn]
    orders_by_payment_id: dict[str, Order]
    refunds_by_parent: dict[str, list[ReconTxn]]
    settlements: dict[str, SettlementMeta]
    bank_by_utr: dict[str, list[BankTxn]]
    bank_rows: list[BankTxn]


class ExceptionFactory:
    def __init__(self):
        self._n = 0

    def make(
        self,
        stage: str,
        reason_code: str,
        entities: dict,
        expected: dict,
        actual: dict,
        amount_impact_paise: int,
        tolerance_applied_paise: int,
        rule_trace: list[str],
        is_reconcilable: bool,
    ) -> Exception_:
        self._n += 1
        return Exception_(
            exception_id=f"exc_{self._n:04d}",
            stage=stage,
            reason_code=reason_code,
            entities=entities,
            expected=expected,
            actual=actual,
            amount_impact_paise=amount_impact_paise,
            tolerance_applied_paise=tolerance_applied_paise,
            rule_trace=rule_trace,
            is_reconcilable=is_reconcilable,
        )


# ---------------------------------------------------------------------------
# SS5.1 Normalize
# ---------------------------------------------------------------------------
def load_csvs(orders_csv: str, recon_csv: str, bank_csv: str) -> tuple[list[Order], list[ReconTxn], list[BankTxn]]:
    orders_df = pd.read_csv(orders_csv, keep_default_na=False, dtype={"payment_id": str})
    recon_df = pd.read_csv(recon_csv, keep_default_na=False, dtype={"parent_payment_id": str, "order_id": str})
    bank_df = pd.read_csv(bank_csv, keep_default_na=False)

    orders = [
        Order(
            order_id=r.order_id,
            created_at=r.created_at,
            gross_amount_paise=int(r.gross_amount_paise),
            currency=r.currency,
            method=r.method,
            payment_id=r.payment_id or None,
            customer_id=r.customer_id,
            status=r.status,
        )
        for r in orders_df.itertuples()
    ]
    recon_txns = [
        ReconTxn(
            settlement_id=r.settlement_id,
            settlement_utr=r.settlement_utr,
            settled_at=r.settled_at,
            on_hold=bool(r.on_hold) if not isinstance(r.on_hold, str) else r.on_hold == "True",
            is_instant=bool(r.is_instant) if not isinstance(r.is_instant, str) else r.is_instant == "True",
            entity_type=r.entity_type,
            entity_id=r.entity_id,
            parent_payment_id=r.parent_payment_id or None,
            order_id=r.order_id or None,
            method=r.method,
            captured_at=r.captured_at,
            gross_amount_paise=int(r.gross_amount_paise),
            fee_paise=int(r.fee_paise),
            tax_paise=int(r.tax_paise),
            credit_paise=int(r.credit_paise),
            debit_paise=int(r.debit_paise),
        )
        for r in recon_df.itertuples()
    ]
    bank_txns = [
        BankTxn(
            txn_date=r.txn_date,
            value_date=r.value_date,
            utr=r.utr,
            narration=r.narration,
            credit_paise=int(r.credit_paise),
            debit_paise=int(r.debit_paise),
            balance_paise=int(r.balance_paise),
            bank_ref_no=r.bank_ref_no,
        )
        for r in bank_df.itertuples()
    ]
    return orders, recon_txns, bank_txns


def normalize(orders: list[Order], recon_txns: list[ReconTxn], bank_txns: list[BankTxn]) -> NormalizedData:
    payments_by_id: dict[str, ReconTxn] = {}
    orders_by_payment_id: dict[str, Order] = {o.payment_id: o for o in orders if o.payment_id}
    refunds_by_parent: dict[str, list[ReconTxn]] = defaultdict(list)
    settlements: dict[str, SettlementMeta] = {}
    bank_by_utr: dict[str, list[BankTxn]] = defaultdict(list)

    for t in recon_txns:
        sm = settlements.get(t.settlement_id)
        if sm is None:
            sm = SettlementMeta(
                settlement_id=t.settlement_id,
                settlement_utr=t.settlement_utr,
                settled_at=t.settled_at,
                on_hold=t.on_hold,
                is_instant=t.is_instant,
            )
            settlements[t.settlement_id] = sm
        sm.txns.append(t)

        if t.entity_type == EntityType.payment:
            payments_by_id[t.entity_id] = t
        elif t.entity_type == EntityType.refund and t.parent_payment_id:
            refunds_by_parent[t.parent_payment_id].append(t)

    for bt in bank_txns:
        bank_by_utr[bt.utr].append(bt)

    return NormalizedData(
        orders=orders,
        payments_by_id=payments_by_id,
        orders_by_payment_id=orders_by_payment_id,
        refunds_by_parent=dict(refunds_by_parent),
        settlements=settlements,
        bank_by_utr=dict(bank_by_utr),
        bank_rows=bank_txns,
    )


# ---------------------------------------------------------------------------
# SS5.2 Stage A -- Order <-> Payment
# ---------------------------------------------------------------------------
def stage_a(data: NormalizedData, ef: ExceptionFactory, tol_abs: int, tol_rel: float) -> tuple[list[MatchRecord], list[Exception_]]:
    matches: list[MatchRecord] = []
    exceptions: list[Exception_] = []
    referenced_payment_ids: set[str] = set()

    for order in data.orders:
        pay = data.payments_by_id.get(order.payment_id) if order.payment_id else None
        if pay is None:
            exceptions.append(
                ef.make(
                    stage="A",
                    reason_code="ORPHAN_ORDER",
                    entities={"order_id": order.order_id, "orders": [order.order_id]},
                    expected={"payment_id": "present"},
                    actual={"payment_id": order.payment_id or None},
                    amount_impact_paise=order.gross_amount_paise,
                    tolerance_applied_paise=0,
                    rule_trace=["A.order_payment_lookup:not_found"],
                    is_reconcilable=False,
                )
            )
            continue

        referenced_payment_ids.add(order.payment_id)
        if pay.gross_amount_paise != order.gross_amount_paise:
            exceptions.append(
                ef.make(
                    stage="A",
                    reason_code="AMOUNT_MISMATCH_ORDER_PAYMENT",
                    entities={"order_id": order.order_id, "payment_id": pay.entity_id, "orders": [order.order_id]},
                    expected={"gross_amount_paise": order.gross_amount_paise},
                    actual={"gross_amount_paise": pay.gross_amount_paise},
                    amount_impact_paise=abs(pay.gross_amount_paise - order.gross_amount_paise),
                    tolerance_applied_paise=tol_abs,
                    rule_trace=["A.amount_compare:mismatch"],
                    is_reconcilable=False,
                )
            )
        else:
            matches.append(
                MatchRecord(
                    stage="A",
                    entity_id=order.order_id,
                    reason_code="AUTO_MATCHED",
                    details={"payment_id": pay.entity_id},
                )
            )

    for pid, pay in data.payments_by_id.items():
        if pid not in referenced_payment_ids:
            exceptions.append(
                ef.make(
                    stage="A",
                    reason_code="PAYMENT_NO_ORDER",
                    entities={"payment_id": pid, "orders": []},
                    expected={"order_reference": "present"},
                    actual={"order_reference": None},
                    amount_impact_paise=pay.gross_amount_paise,
                    tolerance_applied_paise=0,
                    rule_trace=["A.payment_order_lookup:not_found"],
                    is_reconcilable=False,
                )
            )

    return matches, exceptions


# ---------------------------------------------------------------------------
# SS5.3 Stage B -- Settlement net validation (+ cross-settlement refunds)
# ---------------------------------------------------------------------------
def _resolve_unambiguous_bank_credit(sm: SettlementMeta, data: NormalizedData) -> Optional[int]:
    if sm.on_hold:
        return None
    cands = data.bank_by_utr.get(sm.settlement_utr, [])
    if len(cands) == 1:
        return cands[0].credit_paise
    return None


def stage_b(
    data: NormalizedData,
    ef: ExceptionFactory,
    fee_rates: dict[str, float],
    gst_rate: float,
    instant_premium: float,
    tol_abs: int,
    tol_rel: float,
) -> tuple[list[MatchRecord], list[Exception_]]:
    matches: list[MatchRecord] = []
    exceptions: list[Exception_] = []

    for sm in data.settlements.values():
        expected = 0
        rule_trace: list[str] = []

        for t in sm.txns:
            if t.entity_type == EntityType.payment:
                base_rate = fee_rates[t.method.value if hasattr(t.method, "value") else t.method]
                exp_rate = effective_fee_rate(base_rate, sm.is_instant, instant_premium)
                exp_fee = calc_fee_paise(t.gross_amount_paise, exp_rate)
                fee_diff = abs(t.fee_paise - exp_fee)
                fee_ok = within_tolerance(fee_diff, exp_fee, tol_abs, tol_rel)
                if not fee_ok:
                    alt_rate = base_rate if sm.is_instant else base_rate + instant_premium
                    exp_fee_alt = calc_fee_paise(t.gross_amount_paise, alt_rate)
                    alt_diff = abs(t.fee_paise - exp_fee_alt)
                    if within_tolerance(alt_diff, exp_fee_alt, tol_abs, tol_rel):
                        matches.append(
                            MatchRecord(
                                stage="B",
                                entity_id=t.entity_id,
                                reason_code="FEE_VARIANCE_INSTANT_OK",
                                details={"settlement_id": sm.settlement_id, "expected_fee_paise": exp_fee, "alt_fee_paise": exp_fee_alt, "actual_fee_paise": t.fee_paise},
                            )
                        )
                    else:
                        exceptions.append(
                            ef.make(
                                stage="B",
                                reason_code="FEE_MISMATCH",
                                entities={"payment_id": t.entity_id, "settlement_id": sm.settlement_id},
                                expected={"fee_paise": exp_fee},
                                actual={"fee_paise": t.fee_paise},
                                amount_impact_paise=fee_diff,
                                tolerance_applied_paise=tol_abs,
                                rule_trace=["B.fee_check:mismatch", "B.fee_check.alt_rate:mismatch"],
                                is_reconcilable=False,
                            )
                        )

                exp_gst = calc_gst_paise(t.fee_paise, gst_rate)
                gst_diff = abs(t.tax_paise - exp_gst)
                if not within_tolerance(gst_diff, exp_gst, tol_abs, tol_rel):
                    exceptions.append(
                        ef.make(
                            stage="B",
                            reason_code="GST_MISMATCH",
                            entities={"payment_id": t.entity_id, "settlement_id": sm.settlement_id},
                            expected={"tax_paise": exp_gst},
                            actual={"tax_paise": t.tax_paise},
                            amount_impact_paise=gst_diff,
                            tolerance_applied_paise=tol_abs,
                            rule_trace=["B.gst_check:mismatch"],
                            is_reconcilable=False,
                        )
                    )

                expected += t.gross_amount_paise - t.fee_paise - t.tax_paise

            elif t.entity_type == EntityType.refund:
                parent = data.payments_by_id.get(t.parent_payment_id) if t.parent_payment_id else None
                if parent is None:
                    exceptions.append(
                        ef.make(
                            stage="B",
                            reason_code="UNLINKED_REFUND",
                            entities={"refund_id": t.entity_id, "settlement_id": sm.settlement_id},
                            expected={"parent_payment_id": "present"},
                            actual={"parent_payment_id": t.parent_payment_id},
                            amount_impact_paise=t.debit_paise,
                            tolerance_applied_paise=0,
                            rule_trace=["B.refund_parent_lookup:not_found"],
                            is_reconcilable=False,
                        )
                    )
                elif parent.settlement_id != sm.settlement_id:
                    matches.append(
                        MatchRecord(
                            stage="B",
                            entity_id=t.entity_id,
                            reason_code="REFUND_IN_LATER_SETTLEMENT_OK",
                            details={"settlement_id": sm.settlement_id, "parent_settlement_id": parent.settlement_id},
                        )
                    )
                else:
                    matches.append(
                        MatchRecord(stage="B", entity_id=t.entity_id, reason_code="AUTO_MATCHED", details={"settlement_id": sm.settlement_id})
                    )
                expected -= t.debit_paise

            elif t.entity_type == EntityType.adjustment:
                if not t.parent_payment_id:
                    exceptions.append(
                        ef.make(
                            stage="B",
                            reason_code="UNRECONCILED_ADJUSTMENT",
                            entities={"adjustment_id": t.entity_id, "settlement_id": sm.settlement_id},
                            expected={"parent_payment_id": "present"},
                            actual={"parent_payment_id": None},
                            amount_impact_paise=t.debit_paise,
                            tolerance_applied_paise=0,
                            rule_trace=["B.adjustment_parent_lookup:not_found"],
                            is_reconcilable=False,
                        )
                    )
                else:
                    expected -= t.debit_paise
                    matches.append(
                        MatchRecord(stage="B", entity_id=t.entity_id, reason_code="AUTO_MATCHED", details={"settlement_id": sm.settlement_id})
                    )

        sm.expected_net_paise = expected

        actual_net = _resolve_unambiguous_bank_credit(sm, data)
        if actual_net is None:
            rule_trace.append("B.settlement_net:deferred_to_stage_c(ambiguous_or_missing_bank_row)")
            continue

        diff = abs(expected - actual_net)
        if diff == 0:
            matches.append(
                MatchRecord(stage="B", entity_id=sm.settlement_id, reason_code="AUTO_MATCHED", details={"expected_net_paise": expected, "actual_net_paise": actual_net})
            )
        elif within_tolerance(diff, expected, tol_abs, tol_rel):
            matches.append(
                MatchRecord(
                    stage="B",
                    entity_id=sm.settlement_id,
                    reason_code="ROUNDING_DRIFT_ABSORBED",
                    details={"expected_net_paise": expected, "actual_net_paise": actual_net, "drift_paise": expected - actual_net},
                )
            )
        else:
            exceptions.append(
                ef.make(
                    stage="B",
                    reason_code="SETTLEMENT_NET_MISMATCH",
                    entities={"settlement_id": sm.settlement_id},
                    expected={"net_paise": expected},
                    actual={"net_paise": actual_net},
                    amount_impact_paise=diff,
                    tolerance_applied_paise=tol_abs,
                    rule_trace=["B.settlement_net:mismatch"],
                    is_reconcilable=False,
                )
            )

    return matches, exceptions


# ---------------------------------------------------------------------------
# SS5.4 Stage C -- Settlement <-> Bank credit
# ---------------------------------------------------------------------------
def _stage_c_single(sm: SettlementMeta, bank_row: BankTxn, ef: ExceptionFactory, tol_abs: int, tol_rel: float, matches: list[MatchRecord], exceptions: list[Exception_], claimed: set[int]) -> None:
    """One settlement, one unambiguous bank candidate: direct amount check."""
    expected_net = sm.expected_net_paise
    diff = abs(bank_row.credit_paise - expected_net)
    if within_tolerance(diff, expected_net, tol_abs, tol_rel):
        claimed.add(id(bank_row))
        matches.append(
            MatchRecord(stage="C", entity_id=sm.settlement_id, reason_code="AUTO_MATCHED", details={"utr": sm.settlement_utr, "bank_credit_paise": bank_row.credit_paise})
        )
    else:
        exceptions.append(
            ef.make(
                stage="C",
                reason_code="MISSING_IN_BANK",
                entities={"settlement_id": sm.settlement_id, "utr": sm.settlement_utr},
                expected={"credit_paise": expected_net},
                actual={"credit_paise": bank_row.credit_paise},
                amount_impact_paise=diff,
                tolerance_applied_paise=tol_abs,
                rule_trace=["C.utr_lookup:1 candidate", "C.amount_check:mismatch"],
                is_reconcilable=False,
            )
        )


def _stage_c_fallback(sm: SettlementMeta, data: NormalizedData, ef: ExceptionFactory, tol_abs: int, tol_rel: float, matches: list[MatchRecord], exceptions: list[Exception_], claimed: set[int]) -> None:
    """No bank row shares this settlement's UTR at all: search a date+amount
    window and fall back to fuzzy narration matching (SS5.4, SS7.2)."""
    expected_net = sm.expected_net_paise
    window = [
        b
        for b in data.bank_rows
        if id(b) not in claimed
        and sm.settled_at <= b.value_date <= sm.settled_at + pd.Timedelta(days=FALLBACK_WINDOW_DAYS)
        and within_tolerance(abs(b.credit_paise - expected_net), expected_net, tol_abs, tol_rel)
    ]
    if len(window) == 1:
        fz = fuzzy_score(window[0].narration, sm.settlement_utr)
        if fz["score"] >= FUZZY_ACCEPT_THRESHOLD:
            claimed.add(id(window[0]))
            matches.append(
                MatchRecord(
                    stage="C",
                    entity_id=sm.settlement_id,
                    reason_code="FUZZY_NARRATION_MATCH",
                    details={"bank_ref_no": window[0].bank_ref_no, "fuzzy_score": fz["score"], "rationale": fz["rationale"]},
                )
            )
            return

    exceptions.append(
        ef.make(
            stage="C",
            reason_code="MISSING_IN_BANK",
            entities={"settlement_id": sm.settlement_id, "utr": sm.settlement_utr},
            expected={"credit_paise": expected_net},
            actual={"credit_paise": None},
            amount_impact_paise=expected_net,
            tolerance_applied_paise=tol_abs,
            rule_trace=["C.utr_lookup:0 candidates", f"C.fallback_window:{len(window)} candidates"],
            is_reconcilable=False,
        )
    )


def stage_c(data: NormalizedData, ef: ExceptionFactory, tol_abs: int, tol_rel: float) -> tuple[list[MatchRecord], list[Exception_]]:
    """Settlements are grouped by UTR before resolution (not processed
    one-by-one against a shrinking claimed-set) so that when a UTR is
    genuinely shared by more than one settlement, every settlement in that
    group is resolved via the duplicate-UTR path and tagged consistently --
    instead of only the first-processed settlement getting the
    DUPLICATE_UTR_RESOLVED tag while a later one quietly narrows down to a
    lone candidate and reads as a plain AUTO_MATCHED. See DECISIONS.md."""
    matches: list[MatchRecord] = []
    exceptions: list[Exception_] = []
    claimed: set[int] = set()  # id() of claimed BankTxn objects

    utr_groups: dict[str, list[SettlementMeta]] = defaultdict(list)
    for sm in data.settlements.values():
        if sm.on_hold:
            exceptions.append(
                ef.make(
                    stage="C",
                    reason_code="MISSING_IN_BANK",
                    entities={"settlement_id": sm.settlement_id, "utr": sm.settlement_utr},
                    expected={"credit_paise": sm.expected_net_paise},
                    actual={"credit_paise": None, "reason": "on_hold"},
                    amount_impact_paise=sm.expected_net_paise,
                    tolerance_applied_paise=tol_abs,
                    rule_trace=["C.on_hold:true"],
                    is_reconcilable=False,
                )
            )
            continue
        utr_groups[sm.settlement_utr].append(sm)

    for utr, group in utr_groups.items():
        bank_cands = list(data.bank_by_utr.get(utr, []))
        ambiguous = len(group) > 1 or len(bank_cands) > 1

        if not ambiguous:
            sm = group[0]
            if len(bank_cands) == 1:
                _stage_c_single(sm, bank_cands[0], ef, tol_abs, tol_rel, matches, exceptions, claimed)
            else:
                _stage_c_fallback(sm, data, ef, tol_abs, tol_rel, matches, exceptions, claimed)
            continue

        # Genuine ambiguity: >=2 settlements sharing this UTR, and/or >=2 bank
        # rows under it. Deterministic tie-break (SS5.4): resolve settlements
        # in settlement_id order, each taking its argmin over amount diff,
        # then date diff, then bank_ref_no -- among currently-unclaimed rows.
        for sm in sorted(group, key=lambda s: s.settlement_id):
            expected_net = sm.expected_net_paise
            remaining = [b for b in bank_cands if id(b) not in claimed]
            if not remaining:
                exceptions.append(
                    ef.make(
                        stage="C",
                        reason_code="DUPLICATE_UTR_UNRESOLVED",
                        entities={"settlement_id": sm.settlement_id, "utr": utr},
                        expected={"credit_paise": expected_net},
                        actual={"credit_paise": []},
                        amount_impact_paise=expected_net,
                        tolerance_applied_paise=tol_abs,
                        rule_trace=[f"C.utr_lookup:{len(bank_cands)} candidates in group", "C.argmin:no_candidates_remaining"],
                        is_reconcilable=False,
                    )
                )
                continue
            pick = min(remaining, key=lambda b: (abs(b.credit_paise - expected_net), abs((b.value_date - sm.settled_at).total_seconds()), b.bank_ref_no))
            diff = abs(pick.credit_paise - expected_net)
            if within_tolerance(diff, expected_net, tol_abs, tol_rel):
                claimed.add(id(pick))
                matches.append(
                    MatchRecord(
                        stage="C",
                        entity_id=sm.settlement_id,
                        reason_code="DUPLICATE_UTR_RESOLVED",
                        details={"utr": utr, "bank_credit_paise": pick.credit_paise, "candidates": len(bank_cands)},
                    )
                )
            else:
                exceptions.append(
                    ef.make(
                        stage="C",
                        reason_code="DUPLICATE_UTR_UNRESOLVED",
                        entities={"settlement_id": sm.settlement_id, "utr": utr},
                        expected={"credit_paise": expected_net},
                        actual={"credit_paise": [c.credit_paise for c in bank_cands]},
                        amount_impact_paise=diff,
                        tolerance_applied_paise=tol_abs,
                        rule_trace=[f"C.utr_lookup:{len(bank_cands)} candidates in group", "C.argmin:best_still_out_of_tolerance"],
                        is_reconcilable=False,
                    )
                )

    for b in data.bank_rows:
        if id(b) not in claimed:
            exceptions.append(
                ef.make(
                    stage="C",
                    reason_code="MISSING_IN_SETTLEMENT",
                    entities={"utr": b.utr, "bank_ref_no": b.bank_ref_no},
                    expected={"settlement_id": None},
                    actual={"credit_paise": b.credit_paise},
                    amount_impact_paise=b.credit_paise,
                    tolerance_applied_paise=0,
                    rule_trace=["C.settlement_lookup:not_found"],
                    is_reconcilable=False,
                )
            )

    return matches, exceptions


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def _tag_multi_day_settlements(data: NormalizedData, matches: list[MatchRecord]) -> None:
    """Stage-B settlement matches get an extra MULTI_DAY_SETTLEMENT_OK tag
    when their txns span more than one distinct capture date. This is a
    presentation-layer tag, not a separate pass/fail check."""
    by_entity: dict[str, MatchRecord] = {m.entity_id: m for m in matches if m.stage == "B"}
    for sm in data.settlements.values():
        capture_dates = {t.captured_at.date() if hasattr(t.captured_at, "date") else t.captured_at for t in sm.txns}
        if len(capture_dates) > 1:
            m = by_entity.get(sm.settlement_id)
            if m is not None:
                m.tags.append("MULTI_DAY_SETTLEMENT_OK")


def reconcile(
    orders: list[Order],
    recon_txns: list[ReconTxn],
    bank_txns: list[BankTxn],
    fee_rates: dict[str, float],
    gst_rate: float,
    instant_premium: float,
    tol_abs: int,
    tol_rel: float,
) -> ReconResult:
    data = normalize(orders, recon_txns, bank_txns)
    ef = ExceptionFactory()

    a_matches, a_exc = stage_a(data, ef, tol_abs, tol_rel)
    b_matches, b_exc = stage_b(data, ef, fee_rates, gst_rate, instant_premium, tol_abs, tol_rel)
    _tag_multi_day_settlements(data, b_matches)
    c_matches, c_exc = stage_c(data, ef, tol_abs, tol_rel)

    matches = a_matches + b_matches + c_matches
    exceptions = a_exc + b_exc + c_exc
    stage_counts = {
        "A": len(a_matches),
        "B": len(b_matches),
        "C": len(c_matches),
        "exceptions_A": len(a_exc),
        "exceptions_B": len(b_exc),
        "exceptions_C": len(c_exc),
    }
    return ReconResult(matches=matches, exceptions=exceptions, stage_counts=stage_counts)
