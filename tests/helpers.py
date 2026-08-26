from datetime import datetime

from engine.models import BankTxn, Order, ReconTxn

BASE = datetime(2026, 7, 1, 9, 0, 0)

FEE_RATES = {"upi": 0.0, "netbanking": 0.019, "card_domestic": 0.02, "wallet": 0.02, "card_international": 0.03}
GST_RATE = 0.18
INSTANT_PREMIUM = 0.0025
TOL_ABS = 100
TOL_REL = 0.001


def make_order(order_id, payment_id, gross, method="upi", **kw):
    return Order(
        order_id=order_id,
        created_at=BASE,
        gross_amount_paise=gross,
        method=method,
        payment_id=payment_id,
        customer_id="cust_1",
        status="captured" if payment_id else "failed",
        **kw,
    )


def make_payment_txn(entity_id, settlement_id, utr, order_id, gross, fee, tax, method="upi", settled_at=BASE, on_hold=False, is_instant=False, captured_at=BASE):
    return ReconTxn(
        settlement_id=settlement_id,
        settlement_utr=utr,
        settled_at=settled_at,
        on_hold=on_hold,
        is_instant=is_instant,
        entity_type="payment",
        entity_id=entity_id,
        order_id=order_id,
        method=method,
        captured_at=captured_at,
        gross_amount_paise=gross,
        fee_paise=fee,
        tax_paise=tax,
        credit_paise=gross - fee - tax,
        debit_paise=0,
    )


def make_refund_txn(entity_id, settlement_id, utr, parent_payment_id, debit, method="upi", settled_at=BASE, on_hold=False, is_instant=False, captured_at=BASE):
    return ReconTxn(
        settlement_id=settlement_id,
        settlement_utr=utr,
        settled_at=settled_at,
        on_hold=on_hold,
        is_instant=is_instant,
        entity_type="refund",
        entity_id=entity_id,
        parent_payment_id=parent_payment_id,
        method=method,
        captured_at=captured_at,
        gross_amount_paise=debit,
        fee_paise=0,
        tax_paise=0,
        credit_paise=0,
        debit_paise=debit,
    )


def make_adjustment_txn(entity_id, settlement_id, utr, parent_payment_id, debit, method="upi", settled_at=BASE, captured_at=BASE):
    return ReconTxn(
        settlement_id=settlement_id,
        settlement_utr=utr,
        settled_at=settled_at,
        entity_type="adjustment",
        entity_id=entity_id,
        parent_payment_id=parent_payment_id,
        method=method,
        captured_at=captured_at,
        gross_amount_paise=0,
        fee_paise=0,
        tax_paise=0,
        credit_paise=0,
        debit_paise=debit,
    )


def make_bank_row(utr, credit, value_date=BASE, narration=None, bank_ref="ref1"):
    return BankTxn(
        txn_date=value_date,
        value_date=value_date,
        utr=utr,
        narration=narration or f"RAZORPAY SOFTWARE PVT LTD/{utr}/SETTLEMENT",
        credit_paise=credit,
        debit_paise=0,
        balance_paise=1_000_000,
        bank_ref_no=bank_ref,
    )
