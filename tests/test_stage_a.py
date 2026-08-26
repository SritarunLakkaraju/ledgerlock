from engine.reconcile import ExceptionFactory, normalize, stage_a
from tests.helpers import TOL_ABS, TOL_REL, make_order, make_payment_txn


def test_auto_matched():
    order = make_order("order_1", "pay_1", 100_000)
    pay = make_payment_txn("pay_1", "setl_1", "utr1", "order_1", 100_000, 0, 0)
    data = normalize([order], [pay], [])
    matches, exceptions = stage_a(data, ExceptionFactory(), TOL_ABS, TOL_REL)
    assert len(matches) == 1 and matches[0].reason_code == "AUTO_MATCHED"
    assert exceptions == []


def test_orphan_order_no_payment_id():
    order = make_order("order_1", None, 100_000)
    data = normalize([order], [], [])
    matches, exceptions = stage_a(data, ExceptionFactory(), TOL_ABS, TOL_REL)
    assert matches == []
    assert len(exceptions) == 1
    assert exceptions[0].reason_code == "ORPHAN_ORDER"
    assert exceptions[0].is_reconcilable is False


def test_orphan_order_dangling_payment_id():
    order = make_order("order_1", "pay_missing", 100_000)
    data = normalize([order], [], [])
    matches, exceptions = stage_a(data, ExceptionFactory(), TOL_ABS, TOL_REL)
    assert len(exceptions) == 1
    assert exceptions[0].reason_code == "ORPHAN_ORDER"


def test_amount_mismatch_order_payment():
    order = make_order("order_1", "pay_1", 100_000)
    pay = make_payment_txn("pay_1", "setl_1", "utr1", "order_1", 99_000, 0, 0)
    data = normalize([order], [pay], [])
    matches, exceptions = stage_a(data, ExceptionFactory(), TOL_ABS, TOL_REL)
    assert matches == []
    assert len(exceptions) == 1
    assert exceptions[0].reason_code == "AMOUNT_MISMATCH_ORDER_PAYMENT"
    assert exceptions[0].amount_impact_paise == 1_000


def test_payment_no_order():
    pay = make_payment_txn("pay_1", "setl_1", "utr1", "order_1", 100_000, 0, 0)
    data = normalize([], [pay], [])
    matches, exceptions = stage_a(data, ExceptionFactory(), TOL_ABS, TOL_REL)
    assert matches == []
    assert len(exceptions) == 1
    assert exceptions[0].reason_code == "PAYMENT_NO_ORDER"
