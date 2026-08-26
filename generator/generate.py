"""COMPONENT 1 -- Synthetic data generator.

Produces orders.csv, razorpay_recon.csv, bank_statement.csv, ground_truth.json
from a seeded RNG. ground_truth.json is never read by the engine at recon
time -- it exists purely for the metrics stage (COMPONENT 3) to score the
engine honestly.

Design notes (things this spec left silent, decided here -- see DECISIONS.md):
  * A settlement's "actual net" (what really got credited to the bank) is
    always exactly its computed net using the same subtraction rules the
    engine's Stage B pseudocode uses (payments net summed; ALL refunds
    subtracted regardless of parent linkage; only PARENT-LINKED adjustments
    subtracted) -- except when the `rounding_drift` anomaly perturbs it by a
    few paise (kept within tolerance). This keeps each injected anomaly
    isolated to a single, predictable reason code instead of cascading into
    unrelated exceptions.
  * Each settlement gets at most one "primary" injected anomaly among
    {rounding_drift, duplicate_utr, missing_in_bank, fee_variance_instant,
    adjustment-host}. `multi_day_settlement` is structural (falls out of the
    bucketing merge step) and is only recorded as a settlement's *ground
    truth* anomaly when it has no other primary anomaly, though the engine
    will still tag MULTI_DAY_SETTLEMENT_OK on any multi-day settlement
    regardless of what else is going on with it.
  * Settlement UTRs and bank ref numbers are synthetic random alnum strings;
    narration templates are dirtied per SS4.2 (random casing, ~20% truncated
    so they don't contain the full UTR).
"""
from __future__ import annotations

import argparse
import json
import random
import string
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from engine.money import calc_fee_paise, calc_gst_paise, calc_net_paise, effective_fee_rate
from generator.config import GeneratorConfig, load_config

BASE_DATE = date(2026, 7, 1)
WINDOW_DAYS = 14
INSTANT_SETTLEMENT_RATE = 0.15  # generator-only constant; not a spec anomaly rate (see DECISIONS.md)

METHOD_WEIGHTS = {
    "upi": 0.45,
    "card_domestic": 0.30,
    "netbanking": 0.15,
    "wallet": 0.07,
    "card_international": 0.03,
}

NARRATION_TEMPLATES_WEIGHTED = [
    ("RAZORPAY SOFTWARE PVT LTD/{utr}/SETTLEMENT", 0.35),
    ("RZPY SETTLMNT {utr8}", 0.20),  # truncated -> no full UTR
    ("NEFT CR-RAZORPAYSOF-{utr}", 0.25),
    ("UPI/{utr}/RAZORPAY", 0.20),
]


@dataclass
class Payment:
    payment_id: str
    order_id: str
    method: str
    gross_paise: int
    captured_at: datetime
    fee_paise: int = 0
    tax_paise: int = 0
    settlement_id: str | None = None


@dataclass
class Refund:
    refund_id: str
    parent_payment_id: str
    debit_paise: int
    captured_at: datetime
    settlement_id: str
    injected_anomaly: str | None = None


@dataclass
class Adjustment:
    adjustment_id: str
    parent_payment_id: str | None
    debit_paise: int
    captured_at: datetime
    settlement_id: str


@dataclass
class Settlement:
    settlement_id: str
    utr: str
    settled_at: datetime
    capture_dates: set[date] = field(default_factory=set)
    is_instant: bool = False
    on_hold: bool = False
    payments: list[Payment] = field(default_factory=list)
    refunds: list[Refund] = field(default_factory=list)
    adjustments: list[Adjustment] = field(default_factory=list)
    primary_anomaly: str | None = None
    computed_net_paise: int = 0
    actual_net_paise: int = 0


def _id(prefix: str, n: int) -> str:
    return f"{prefix}_{n:04d}"


def _count(rate: float, population: int) -> int:
    """round(rate * population), floored to at least 1 whenever rate > 0 and the
    population is non-empty. With only a handful of settlements per run, plain
    rounding floors every low-rate settlement-level anomaly (duplicate_utr,
    missing_in_bank, missing_in_settlement, adjustment) to zero -- which would
    silently violate the "≥8 anomaly types each caught" definition of done.
    See DECISIONS.md."""
    if rate <= 0 or population <= 0:
        return 0
    return max(1, round(rate * population))


def _random_utr(rng: random.Random) -> str:
    return "".join(rng.choices(string.digits, k=6)) + "".join(rng.choices(string.ascii_uppercase + string.digits, k=16))


def _random_ref(rng: random.Random) -> str:
    return "".join(rng.choices(string.ascii_uppercase + string.digits, k=12))


def _dirty_narration(rng: random.Random, utr: str) -> str:
    """~20% of templates (the truncated one) deliberately omit the full UTR (SS4.2)."""
    templates, weights = zip(*NARRATION_TEMPLATES_WEIGHTED)
    tmpl = rng.choices(templates, weights=weights, k=1)[0]
    text = tmpl.format(utr=utr, utr8=utr[:8])
    casing = rng.choice(["upper", "lower", "title", "asis"])
    if casing == "upper":
        text = text.upper()
    elif casing == "lower":
        text = text.lower()
    elif casing == "title":
        text = text.title()
    return text


def _pick_method(rng: random.Random) -> str:
    methods, weights = zip(*METHOD_WEIGHTS.items())
    return rng.choices(methods, weights=weights, k=1)[0]


def _lognormal_amount_paise(rng: random.Random) -> int:
    # log-normal centered so most orders land in the low hundreds of rupees,
    # clipped to the spec's Rs99-Rs25,000 band.
    mu, sigma = 6.7, 0.9  # ln(rupees)
    rupees = rng.lognormvariate(mu, sigma)
    rupees = max(99.0, min(25_000.0, rupees))
    return int(round(rupees * 100))


class Generator:
    def __init__(self, cfg: GeneratorConfig, seed: int | None = None, n_orders: int | None = None):
        self.cfg = cfg
        self.seed = seed if seed is not None else cfg.seed
        self.n_orders = n_orders if n_orders is not None else cfg.n_orders
        self.rng = random.Random(self.seed)
        self.orders: list[dict] = []
        self.payments: dict[str, Payment] = {}
        self.settlements: list[Settlement] = []
        self.refunds: list[Refund] = []
        self.adjustments: list[Adjustment] = []
        self.stray_bank_rows: list[dict] = []
        self.ground_truth: list[dict] = []
        self._counters = {"order": 0, "pay": 0, "rfnd": 0, "adj": 0, "setl": 0}

    def _next_id(self, prefix: str) -> str:
        self._counters[prefix] += 1
        return _id(prefix, self._counters[prefix])

    # ---- step 1+2: orders & payments -----------------------------------
    def _gen_orders_and_payments(self):
        rates = self.cfg.anomaly_rates
        n_orphan = round(rates.orphan_order * self.n_orders)
        orphan_indices = set(self.rng.sample(range(self.n_orders), k=min(n_orphan, self.n_orders)))

        for i in range(self.n_orders):
            order_id = self._next_id("order")
            offset_days = self.rng.uniform(0, WINDOW_DAYS)
            created_at = datetime.combine(BASE_DATE, datetime.min.time()) + timedelta(
                seconds=int(offset_days * 86400) + self.rng.randint(0, 3599)
            )
            method = _pick_method(self.rng)
            gross = _lognormal_amount_paise(self.rng)
            customer_id = f"cust_{self.rng.randint(1, self.n_orders // 2 + 1):04d}"

            is_orphan = i in orphan_indices
            if is_orphan:
                self.orders.append(
                    {
                        "order_id": order_id,
                        "created_at": created_at,
                        "gross_amount_paise": gross,
                        "currency": "INR",
                        "method": method,
                        "payment_id": "",
                        "customer_id": customer_id,
                        "status": "failed",
                    }
                )
                self.ground_truth.append(
                    {
                        "entity_id": order_id,
                        "entity_type": "order",
                        "true_settlement_id": None,
                        "true_bank_utr": None,
                        "expected_net_paise": None,
                        "injected_anomaly": "orphan_order",
                        "is_reconcilable": False,
                        "expected_reason_code": "ORPHAN_ORDER",
                    }
                )
                continue

            payment_id = self._next_id("pay")
            captured_at = created_at + timedelta(seconds=self.rng.randint(1, 300))
            pay = Payment(payment_id=payment_id, order_id=order_id, method=method, gross_paise=gross, captured_at=captured_at)
            self.payments[payment_id] = pay
            self.orders.append(
                {
                    "order_id": order_id,
                    "created_at": created_at,
                    "gross_amount_paise": gross,
                    "currency": "INR",
                    "method": method,
                    "payment_id": payment_id,
                    "customer_id": customer_id,
                    "status": "captured",
                }
            )
            self.ground_truth.append(
                {
                    "entity_id": order_id,
                    "entity_type": "order",
                    "true_settlement_id": None,
                    "true_bank_utr": None,
                    "expected_net_paise": None,
                    "injected_anomaly": None,
                    "is_reconcilable": True,
                    "expected_reason_code": "AUTO_MATCHED",
                }
            )

    # ---- step 3: bucket payments into settlements -----------------------
    def _bucket_settlements(self):
        by_date: dict[date, list[Payment]] = {}
        for pay in self.payments.values():
            nominal = pay.captured_at.date() + timedelta(days=self.cfg.settlement_cycle_days)
            by_date.setdefault(nominal, []).append(pay)

        current: Settlement | None = None
        for d in sorted(by_date.keys()):
            merge = current is not None and self.rng.random() < self.cfg.anomaly_rates.multi_day_settlement
            if merge:
                current.capture_dates.add(d)
                current.settled_at = datetime.combine(d, datetime.min.time()) + timedelta(hours=9)
                current.payments.extend(by_date[d])
            else:
                if current is not None:
                    self.settlements.append(current)
                sid = self._next_id("setl")
                current = Settlement(
                    settlement_id=sid,
                    utr=_random_utr(self.rng),
                    settled_at=datetime.combine(d, datetime.min.time()) + timedelta(hours=9),
                    capture_dates={d},
                    payments=list(by_date[d]),
                )
            for p in by_date[d]:
                p.settlement_id = current.settlement_id
        if current is not None:
            self.settlements.append(current)

        self.settlements.sort(key=lambda s: s.settled_at)

        n_instant = round(INSTANT_SETTLEMENT_RATE * len(self.settlements))
        for s in self.rng.sample(self.settlements, k=min(n_instant, len(self.settlements))):
            s.is_instant = True

    # ---- step 4a: fee/gst per payment (+ fee_variance_instant anomaly) --
    def _compute_fees(self):
        rates = self.cfg.anomaly_rates
        instant_settlements = [s for s in self.settlements if s.is_instant]
        # rate is "of settlements" per config.yaml comment; sampled from the instant subset.
        n_variance = min(_count(rates.fee_variance_instant, len(self.settlements)), len(instant_settlements))
        variance_settlements = set(
            s.settlement_id for s in self.rng.sample(instant_settlements, k=min(n_variance, len(instant_settlements)))
        )

        for s in self.settlements:
            has_variance = s.settlement_id in variance_settlements
            if has_variance:
                s.primary_anomaly = "fee_variance_instant"
            for p in s.payments:
                base_rate = self.cfg.fee_rates[p.method]
                if has_variance:
                    # Razorpay applied the base rate only, forgetting the instant premium.
                    rate = base_rate
                else:
                    rate = effective_fee_rate(base_rate, s.is_instant, self.cfg.instant_premium)
                p.fee_paise = calc_fee_paise(p.gross_paise, rate)
                p.tax_paise = calc_gst_paise(p.fee_paise, self.cfg.gst_rate)

            if has_variance:
                for p in s.payments:
                    self.ground_truth.append(
                        {
                            "entity_id": p.payment_id,
                            "entity_type": "payment",
                            "true_settlement_id": s.settlement_id,
                            "true_bank_utr": s.utr,
                            "expected_net_paise": calc_net_paise(p.gross_paise, p.fee_paise, p.tax_paise),
                            "injected_anomaly": "fee_variance_instant",
                            "is_reconcilable": True,
                            "expected_reason_code": "FEE_VARIANCE_INSTANT_OK",
                        }
                    )

    # ---- step 4b: refunds ------------------------------------------------
    def _gen_refunds(self):
        rates = self.cfg.anomaly_rates
        eligible = list(self.payments.values())
        self.rng.shuffle(eligible)

        n_same = round(rates.partial_refund_same_settlement * self.n_orders)
        n_later = round(rates.partial_refund_later_settlement * self.n_orders)
        n_full_later = round(rates.full_refund_later_settlement * self.n_orders)

        idx = 0

        def next_payment() -> Payment | None:
            nonlocal idx
            if idx >= len(eligible):
                return None
            p = eligible[idx]
            idx += 1
            return p

        settlement_index = {s.settlement_id: i for i, s in enumerate(self.settlements)}

        # same-settlement partial refunds
        for _ in range(n_same):
            p = next_payment()
            if p is None:
                break
            s = self.settlements[settlement_index[p.settlement_id]]
            amount = int(p.gross_paise * self.rng.uniform(0.2, 0.6))
            refund_id = self._next_id("rfnd")
            r = Refund(
                refund_id=refund_id,
                parent_payment_id=p.payment_id,
                debit_paise=amount,
                captured_at=p.captured_at + timedelta(hours=self.rng.uniform(1, 20)),
                settlement_id=s.settlement_id,
                injected_anomaly="partial_refund_same_settlement",
            )
            self.refunds.append(r)
            s.refunds.append(r)
            self.ground_truth.append(
                {
                    "entity_id": refund_id,
                    "entity_type": "refund",
                    "true_settlement_id": s.settlement_id,
                    "true_bank_utr": s.utr,
                    "expected_net_paise": -amount,
                    "injected_anomaly": "partial_refund_same_settlement",
                    "is_reconcilable": True,
                    "expected_reason_code": "AUTO_MATCHED",
                }
            )

        # later-settlement refunds (partial + full) -- the timing case, SS3.3
        for kind, n, frac_range in (
            ("partial_refund_later_settlement", n_later, (0.2, 0.6)),
            ("full_refund_later_settlement", n_full_later, (1.0, 1.0)),
        ):
            for _ in range(n):
                p = next_payment()
                if p is None:
                    break
                parent_idx = settlement_index[p.settlement_id]
                target_idx = min(parent_idx + self.rng.randint(1, 2), len(self.settlements) - 1)
                if target_idx == parent_idx:
                    continue  # parent already in the last settlement; skip, not truly "later"
                target = self.settlements[target_idx]
                lo, hi = frac_range
                amount = p.gross_paise if lo == hi == 1.0 else int(p.gross_paise * self.rng.uniform(lo, hi))
                refund_id = self._next_id("rfnd")
                r = Refund(
                    refund_id=refund_id,
                    parent_payment_id=p.payment_id,
                    debit_paise=amount,
                    captured_at=target.settled_at - timedelta(days=1),
                    settlement_id=target.settlement_id,
                    injected_anomaly=kind,
                )
                self.refunds.append(r)
                target.refunds.append(r)
                self.ground_truth.append(
                    {
                        "entity_id": refund_id,
                        "entity_type": "refund",
                        "true_settlement_id": target.settlement_id,
                        "true_bank_utr": target.utr,
                        "expected_net_paise": -amount,
                        "injected_anomaly": kind,
                        "is_reconcilable": True,
                        "expected_reason_code": "REFUND_IN_LATER_SETTLEMENT_OK",
                    }
                )

    # ---- step 4c: adjustments --------------------------------------------
    def _gen_adjustments(self):
        rate = self.cfg.anomaly_rates.adjustment
        candidates = [s for s in self.settlements if s.payments and s.primary_anomaly is None]
        n = min(_count(rate, len(self.settlements)), len(candidates))
        chosen = self.rng.sample(candidates, k=n)
        for s in chosen:
            adj_id = self._next_id("adj")
            amount = self.rng.randint(5_000, 50_000)  # Rs50 - Rs500, in paise
            a = Adjustment(
                adjustment_id=adj_id,
                parent_payment_id=None,
                debit_paise=amount,
                captured_at=s.settled_at - timedelta(days=1),
                settlement_id=s.settlement_id,
            )
            self.adjustments.append(a)
            s.adjustments.append(a)
            s.primary_anomaly = "adjustment"
            self.ground_truth.append(
                {
                    "entity_id": adj_id,
                    "entity_type": "adjustment",
                    "true_settlement_id": s.settlement_id,
                    "true_bank_utr": s.utr,
                    "expected_net_paise": None,
                    "injected_anomaly": "adjustment",
                    "is_reconcilable": False,
                    "expected_reason_code": "UNRECONCILED_ADJUSTMENT",
                }
            )

    # ---- step 4d: settlement-level net + rounding_drift / missing_in_bank / duplicate_utr ----
    def _finalize_settlement_nets_and_bank_anomalies(self):
        rates = self.cfg.anomaly_rates

        for s in self.settlements:
            net = 0
            for p in s.payments:
                net += calc_net_paise(p.gross_paise, p.fee_paise, p.tax_paise)
            for r in s.refunds:
                net -= r.debit_paise
            for a in s.adjustments:
                if a.parent_payment_id:
                    net -= a.debit_paise
            s.computed_net_paise = net
            s.actual_net_paise = net

        free = [s for s in self.settlements if s.primary_anomaly is None]

        # rounding_drift: perturb actual net by a few paise, still within tolerance
        drift_pool = [s for s in free if s.primary_anomaly is None]
        n_drift = min(_count(rates.rounding_drift, len(self.settlements)), len(drift_pool))
        for s in self.rng.sample(drift_pool, k=n_drift):
            max_delta = max(1, min(self.cfg.tolerance.abs_paise - 10, 60))
            delta = self.rng.randint(1, max_delta) * self.rng.choice([-1, 1])
            s.actual_net_paise += delta
            s.primary_anomaly = "rounding_drift"

        # missing_in_bank: settlement goes on_hold, no bank row emitted
        hold_pool = [s for s in self.settlements if s.primary_anomaly is None]
        n_missing = min(_count(rates.missing_in_bank, len(self.settlements)), len(hold_pool))
        for s in self.rng.sample(hold_pool, k=n_missing):
            s.on_hold = True
            s.primary_anomaly = "missing_in_bank"

        # duplicate_utr: pair up settlements sharing a UTR (needs >=2 settlements)
        dup_pool = [s for s in self.settlements if s.primary_anomaly is None and not s.on_hold]
        n_dup = min(_count(rates.duplicate_utr, len(self.settlements)), len(dup_pool))
        if 0 < n_dup < 2 and len(dup_pool) >= 2:
            n_dup = 2
        n_dup -= n_dup % 2  # need pairs
        chosen = self.rng.sample(dup_pool, k=n_dup)
        for i in range(0, len(chosen) - 1, 2):
            a, b = chosen[i], chosen[i + 1]
            b.utr = a.utr
            a.primary_anomaly = "duplicate_utr"
            b.primary_anomaly = "duplicate_utr"

    # ---- step 5: bank rows + ground truth for settlements ----------------
    def _gen_bank_rows_and_settlement_gt(self):
        self.bank_rows: list[dict] = []
        balance = 10_000_000_00  # Rs1,00,00,000 opening balance, cosmetic only

        for s in self.settlements:
            multi_day = len(s.capture_dates) > 1
            if s.primary_anomaly is not None:
                anomaly = s.primary_anomaly
            elif multi_day:
                anomaly = "multi_day_settlement"
            else:
                anomaly = None

            reason_map = {
                None: "AUTO_MATCHED",
                "multi_day_settlement": "MULTI_DAY_SETTLEMENT_OK",
                "rounding_drift": "ROUNDING_DRIFT_ABSORBED",
                "missing_in_bank": "MISSING_IN_BANK",
                "duplicate_utr": "DUPLICATE_UTR_RESOLVED",
                "fee_variance_instant": "AUTO_MATCHED",  # settlement net itself is unaffected
                "adjustment": "AUTO_MATCHED",  # net still reconciles; only the adjustment entity is flagged
            }
            reconcilable = anomaly != "missing_in_bank"

            self.ground_truth.append(
                {
                    "entity_id": s.settlement_id,
                    "entity_type": "settlement",
                    "true_settlement_id": s.settlement_id,
                    "true_bank_utr": s.utr,
                    "expected_net_paise": s.computed_net_paise,
                    "injected_anomaly": anomaly,
                    "is_reconcilable": reconcilable,
                    "expected_reason_code": reason_map[anomaly],
                }
            )

            if s.on_hold:
                continue

            value_date = s.settled_at + timedelta(days=self.rng.choice([0, 0, 1]))
            narration = _dirty_narration(self.rng, s.utr)
            balance += s.actual_net_paise
            self.bank_rows.append(
                {
                    "txn_date": value_date,
                    "value_date": value_date,
                    "utr": s.utr,
                    "narration": narration,
                    "credit_paise": s.actual_net_paise,
                    "debit_paise": 0,
                    "balance_paise": balance,
                    "bank_ref_no": _random_ref(self.rng),
                }
            )

        # missing_in_settlement: stray bank credits not tied to any settlement
        n_stray = _count(self.cfg.anomaly_rates.missing_in_settlement, len(self.settlements))
        for i in range(n_stray):
            utr = _random_utr(self.rng)
            amount = self.rng.randint(10_000, 500_000)
            value_date = datetime.combine(BASE_DATE, datetime.min.time()) + timedelta(
                days=self.rng.uniform(2, WINDOW_DAYS + self.cfg.settlement_cycle_days)
            )
            balance += amount
            self.bank_rows.append(
                {
                    "txn_date": value_date,
                    "value_date": value_date,
                    "utr": utr,
                    "narration": "NEFT CR-MISCVENDOR-" + utr[:10],
                    "credit_paise": amount,
                    "debit_paise": 0,
                    "balance_paise": balance,
                    "bank_ref_no": _random_ref(self.rng),
                }
            )
            self.ground_truth.append(
                {
                    "entity_id": f"bank_extra_{i:04d}",
                    "entity_type": "bank_credit",
                    "true_settlement_id": None,
                    "true_bank_utr": utr,
                    "expected_net_paise": None,
                    "injected_anomaly": "missing_in_settlement",
                    "is_reconcilable": False,
                    "expected_reason_code": "MISSING_IN_SETTLEMENT",
                }
            )

    # ---- serialization -----------------------------------------------------
    def _recon_rows(self) -> list[dict]:
        rows = []
        for s in self.settlements:
            for p in s.payments:
                rows.append(
                    {
                        "settlement_id": s.settlement_id,
                        "settlement_utr": s.utr,
                        "settled_at": s.settled_at,
                        "on_hold": s.on_hold,
                        "is_instant": s.is_instant,
                        "entity_type": "payment",
                        "entity_id": p.payment_id,
                        "parent_payment_id": "",
                        "order_id": p.order_id,
                        "method": p.method,
                        "captured_at": p.captured_at,
                        "gross_amount_paise": p.gross_paise,
                        "fee_paise": p.fee_paise,
                        "tax_paise": p.tax_paise,
                        "credit_paise": calc_net_paise(p.gross_paise, p.fee_paise, p.tax_paise),
                        "debit_paise": 0,
                    }
                )
            for r in s.refunds:
                parent = self.payments[r.parent_payment_id]
                rows.append(
                    {
                        "settlement_id": s.settlement_id,
                        "settlement_utr": s.utr,
                        "settled_at": s.settled_at,
                        "on_hold": s.on_hold,
                        "is_instant": s.is_instant,
                        "entity_type": "refund",
                        "entity_id": r.refund_id,
                        "parent_payment_id": r.parent_payment_id,
                        "order_id": parent.order_id,
                        "method": parent.method,
                        "captured_at": r.captured_at,
                        "gross_amount_paise": r.debit_paise,
                        "fee_paise": 0,
                        "tax_paise": 0,
                        "credit_paise": 0,
                        "debit_paise": r.debit_paise,
                    }
                )
            for a in s.adjustments:
                rows.append(
                    {
                        "settlement_id": s.settlement_id,
                        "settlement_utr": s.utr,
                        "settled_at": s.settled_at,
                        "on_hold": s.on_hold,
                        "is_instant": s.is_instant,
                        "entity_type": "adjustment",
                        "entity_id": a.adjustment_id,
                        "parent_payment_id": a.parent_payment_id or "",
                        "order_id": "",
                        "method": "upi",
                        "captured_at": a.captured_at,
                        "gross_amount_paise": 0,
                        "fee_paise": 0,
                        "tax_paise": 0,
                        "credit_paise": 0,
                        "debit_paise": a.debit_paise,
                    }
                )
        rows.sort(key=lambda r: (r["settlement_id"], r["entity_type"], r["entity_id"]))
        return rows

    def run(self, out_dir: str | Path) -> dict:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        self._gen_orders_and_payments()
        self._bucket_settlements()
        self._compute_fees()
        self._gen_refunds()
        self._gen_adjustments()
        self._finalize_settlement_nets_and_bank_anomalies()
        self._gen_bank_rows_and_settlement_gt()

        import pandas as pd

        orders_df = pd.DataFrame(self.orders)
        orders_df.to_csv(out_dir / "orders.csv", index=False)

        recon_df = pd.DataFrame(self._recon_rows())
        recon_df.to_csv(out_dir / "razorpay_recon.csv", index=False)

        bank_df = pd.DataFrame(self.bank_rows)
        bank_df = bank_df.sort_values("value_date").reset_index(drop=True)
        bank_df.to_csv(out_dir / "bank_statement.csv", index=False)

        with open(out_dir / "ground_truth.json", "w") as f:
            json.dump({"entities": self.ground_truth}, f, indent=2, default=str)

        counts = {
            "orders": len(self.orders),
            "payments": len(self.payments),
            "refunds": len(self.refunds),
            "adjustments": len(self.adjustments),
            "settlements": len(self.settlements),
            "bank_rows": len(self.bank_rows),
            "ground_truth_entities": len(self.ground_truth),
        }
        with open(out_dir / "manifest.json", "w") as f:
            json.dump({"seed": self.seed, "n_orders": self.n_orders, "counts": counts}, f, indent=2)
        return counts


def generate(config_path: str = "config.yaml", out_dir: str = "runs/latest", seed: int | None = None, n_orders: int | None = None) -> dict:
    cfg = load_config(config_path)
    gen = Generator(cfg, seed=seed, n_orders=n_orders)
    return gen.run(out_dir)


def main():
    ap = argparse.ArgumentParser(description="Generate LedgerLock synthetic reconciliation data.")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--out", default="runs/latest")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--n-orders", type=int, default=None)
    args = ap.parse_args()
    counts = generate(args.config, args.out, seed=args.seed, n_orders=args.n_orders)
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
