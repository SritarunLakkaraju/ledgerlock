from engine.reconcile import ExceptionFactory, normalize, stage_b
from tests.helpers import (
    FEE_RATES,
    GST_RATE,
    INSTANT_PREMIUM,
    TOL_ABS,
    TOL_REL,
    make_adjustment_txn,
    make_bank_row,
    make_payment_txn,
    make_refund_txn,
)


def run_stage_b(recon_txns, bank_txns):
    data = normalize([], recon_txns, bank_txns)
    matches, exceptions = stage_b(data, ExceptionFactory(), FEE_RATES, GST_RATE, INSTANT_PREMIUM, TOL_ABS, TOL_REL)
    return matches, exceptions


def test_settlement_auto_matched():
    pay = make_payment_txn("pay_1", "setl_1", "utr1", "order_1", 100_000, 2000, 360, method="card_domestic")
    bank = make_bank_row("utr1", 97_640)
    matches, exceptions = run_stage_b([pay], [bank])
    settlement_matches = [m for m in matches if m.entity_id == "setl_1"]
    assert len(settlement_matches) == 1
    assert settlement_matches[0].reason_code == "AUTO_MATCHED"
    assert exceptions == []


def test_rounding_drift_absorbed():
    pay = make_payment_txn("pay_1", "setl_1", "utr1", "order_1", 100_000, 2000, 360, method="card_domestic")
    bank = make_bank_row("utr1", 97_640 - 50)  # 50p drift, within tolerance
    matches, exceptions = run_stage_b([pay], [bank])
    settlement_matches = [m for m in matches if m.entity_id == "setl_1"]
    assert settlement_matches[0].reason_code == "ROUNDING_DRIFT_ABSORBED"
    assert exceptions == []


def test_settlement_net_mismatch():
    pay = make_payment_txn("pay_1", "setl_1", "utr1", "order_1", 100_000, 2000, 360, method="card_domestic")
    bank = make_bank_row("utr1", 97_640 - 5_000)  # way outside tolerance
    matches, exceptions = run_stage_b([pay], [bank])
    assert not any(m.entity_id == "setl_1" for m in matches)
    net_exc = [e for e in exceptions if e.reason_code == "SETTLEMENT_NET_MISMATCH"]
    assert len(net_exc) == 1
    assert net_exc[0].amount_impact_paise == 5_000


def test_fee_mismatch():
    # fee wildly wrong for card_domestic, not explainable by any known rate
    pay = make_payment_txn("pay_1", "setl_1", "utr1", "order_1", 100_000, 9_999, 1_800, method="card_domestic")
    bank = make_bank_row("utr1", 100_000 - 9_999 - 1_800)
    matches, exceptions = run_stage_b([pay], [bank])
    fee_exc = [e for e in exceptions if e.reason_code == "FEE_MISMATCH"]
    assert len(fee_exc) == 1
    assert fee_exc[0].entities["payment_id"] == "pay_1"


def test_gst_mismatch():
    pay = make_payment_txn("pay_1", "setl_1", "utr1", "order_1", 100_000, 2_000, 999, method="card_domestic")
    bank = make_bank_row("utr1", 100_000 - 2_000 - 999)
    matches, exceptions = run_stage_b([pay], [bank])
    gst_exc = [e for e in exceptions if e.reason_code == "GST_MISMATCH"]
    assert len(gst_exc) == 1


def test_fee_variance_instant_ok():
    # instant settlement, but fee stored used the base rate only (premium forgotten)
    pay = make_payment_txn("pay_1", "setl_1", "utr1", "order_1", 100_000, 2_000, 360, method="card_domestic", is_instant=True)
    bank = make_bank_row("utr1", 100_000 - 2_000 - 360)
    matches, exceptions = run_stage_b([pay], [bank])
    variance = [m for m in matches if m.reason_code == "FEE_VARIANCE_INSTANT_OK"]
    assert len(variance) == 1
    assert variance[0].entity_id == "pay_1"
    assert exceptions == []


def test_unlinked_refund():
    pay = make_payment_txn("pay_1", "setl_1", "utr1", "order_1", 100_000, 0, 0, method="upi")
    refund = make_refund_txn("rfnd_1", "setl_1", "utr1", "pay_missing", 10_000)
    bank = make_bank_row("utr1", 100_000 - 10_000)
    matches, exceptions = run_stage_b([pay, refund], [bank])
    unlinked = [e for e in exceptions if e.reason_code == "UNLINKED_REFUND"]
    assert len(unlinked) == 1
    assert unlinked[0].entities["refund_id"] == "rfnd_1"


def test_unreconciled_adjustment():
    pay = make_payment_txn("pay_1", "setl_1", "utr1", "order_1", 100_000, 0, 0, method="upi")
    adj = make_adjustment_txn("adj_1", "setl_1", "utr1", None, 20_000)
    bank = make_bank_row("utr1", 100_000)  # adjustment NOT subtracted since unlinked
    matches, exceptions = run_stage_b([pay, adj], [bank])
    unrec = [e for e in exceptions if e.reason_code == "UNRECONCILED_ADJUSTMENT"]
    assert len(unrec) == 1
    assert unrec[0].amount_impact_paise == 20_000
    # settlement itself still reconciles cleanly -- only the adjustment line is flagged
    assert any(m.entity_id == "setl_1" and m.reason_code == "AUTO_MATCHED" for m in matches)


def test_refund_in_later_settlement_ok():
    pay = make_payment_txn("pay_1", "setl_1", "utr1", "order_1", 100_000, 0, 0, method="upi")
    refund = make_refund_txn("rfnd_1", "setl_2", "utr2", "pay_1", 30_000)
    bank1 = make_bank_row("utr1", 100_000)
    bank2 = make_bank_row("utr2", -30_000)
    matches, exceptions = run_stage_b([pay, refund], [bank1, bank2])
    later = [m for m in matches if m.reason_code == "REFUND_IN_LATER_SETTLEMENT_OK"]
    assert len(later) == 1
    assert later[0].entity_id == "rfnd_1"
