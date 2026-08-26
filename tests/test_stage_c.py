from datetime import timedelta

from engine.reconcile import ExceptionFactory, normalize, stage_b, stage_c
from tests.helpers import BASE, FEE_RATES, GST_RATE, INSTANT_PREMIUM, TOL_ABS, TOL_REL, make_bank_row, make_payment_txn


def run_stage_c(recon_txns, bank_txns):
    data = normalize([], recon_txns, bank_txns)
    ef = ExceptionFactory()
    stage_b(data, ef, FEE_RATES, GST_RATE, INSTANT_PREMIUM, TOL_ABS, TOL_REL)  # populates expected_net_paise
    matches, exceptions = stage_c(data, ef, TOL_ABS, TOL_REL)
    return matches, exceptions


def test_auto_matched():
    pay = make_payment_txn("pay_1", "setl_1", "utr1", "order_1", 100_000, 0, 0, method="upi")
    bank = make_bank_row("utr1", 100_000)
    matches, exceptions = run_stage_c([pay], [bank])
    assert len(matches) == 1 and matches[0].reason_code == "AUTO_MATCHED"
    assert exceptions == []


def test_missing_in_bank_on_hold():
    pay = make_payment_txn("pay_1", "setl_1", "utr1", "order_1", 100_000, 0, 0, method="upi", on_hold=True)
    matches, exceptions = run_stage_c([pay], [])
    assert matches == []
    assert len(exceptions) == 1
    assert exceptions[0].reason_code == "MISSING_IN_BANK"
    assert exceptions[0].actual["reason"] == "on_hold"


def test_missing_in_bank_amount_mismatch():
    pay = make_payment_txn("pay_1", "setl_1", "utr1", "order_1", 100_000, 0, 0, method="upi")
    bank = make_bank_row("utr1", 50_000)  # nowhere near expected 100,000
    matches, exceptions = run_stage_c([pay], [bank])
    assert matches == []
    # the settlement's expected credit never showed up (MISSING_IN_BANK), and
    # the actual 50,000 credit is never claimed by anyone (MISSING_IN_SETTLEMENT) --
    # two honest, distinct exceptions for one underlying discrepancy.
    reasons = {e.reason_code for e in exceptions}
    assert reasons == {"MISSING_IN_BANK", "MISSING_IN_SETTLEMENT"}


def test_duplicate_utr_resolved():
    pay1 = make_payment_txn("pay_1", "setl_1", "utr_shared", "order_1", 100_000, 0, 0, method="upi")
    pay2 = make_payment_txn("pay_2", "setl_2", "utr_shared", "order_2", 50_000, 0, 0, method="upi")
    bank1 = make_bank_row("utr_shared", 100_000, bank_ref="ref_a")
    bank2 = make_bank_row("utr_shared", 50_000, bank_ref="ref_b")
    matches, exceptions = run_stage_c([pay1, pay2], [bank1, bank2])
    resolved = [m for m in matches if m.reason_code == "DUPLICATE_UTR_RESOLVED"]
    assert len(resolved) == 2
    assert {m.entity_id for m in resolved} == {"setl_1", "setl_2"}
    assert exceptions == []


def test_duplicate_utr_unresolved():
    pay1 = make_payment_txn("pay_1", "setl_1", "utr_shared", "order_1", 100_000, 0, 0, method="upi")
    pay2 = make_payment_txn("pay_2", "setl_2", "utr_shared", "order_2", 50_000, 0, 0, method="upi")
    # neither bank row is close to either settlement's expected net
    bank1 = make_bank_row("utr_shared", 10_000, bank_ref="ref_a")
    bank2 = make_bank_row("utr_shared", 12_000, bank_ref="ref_b")
    matches, exceptions = run_stage_c([pay1, pay2], [bank1, bank2])
    unresolved = [e for e in exceptions if e.reason_code == "DUPLICATE_UTR_UNRESOLVED"]
    assert len(unresolved) == 2


def test_fuzzy_narration_match():
    pay = make_payment_txn("pay_1", "setl_1", "utr1", "order_1", 100_000, 0, 0, method="upi")
    # bank's structured utr column is dirty/different, but narration carries the full real UTR,
    # amount matches, and value_date is inside the fallback window -- forces the fuzzy path.
    bank = make_bank_row(
        "SOME_OTHER_BANK_REF_CODE",
        100_000,
        value_date=BASE + timedelta(days=1),
        narration="RAZORPAY SOFTWARE PVT LTD/utr1/SETTLEMENT",
    )
    matches, exceptions = run_stage_c([pay], [bank])
    fuzzy = [m for m in matches if m.reason_code == "FUZZY_NARRATION_MATCH"]
    assert len(fuzzy) == 1
    assert fuzzy[0].entity_id == "setl_1"
    assert exceptions == []


def test_missing_in_settlement_stray_bank_row():
    pay = make_payment_txn("pay_1", "setl_1", "utr1", "order_1", 100_000, 0, 0, method="upi")
    bank = make_bank_row("utr1", 100_000)
    stray = make_bank_row("utr_unrelated", 25_000, bank_ref="stray_ref")
    matches, exceptions = run_stage_c([pay], [bank, stray])
    stray_exc = [e for e in exceptions if e.reason_code == "MISSING_IN_SETTLEMENT"]
    assert len(stray_exc) == 1
    assert stray_exc[0].entities["bank_ref_no"] == "stray_ref"
