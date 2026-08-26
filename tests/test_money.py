from engine.money import (
    calc_fee_paise,
    calc_gst_paise,
    calc_net_paise,
    effective_fee_rate,
    format_inr,
    round_half_up,
    rupees_to_paise,
    within_tolerance,
)

FEE_RATES = {
    "upi": 0.0,
    "netbanking": 0.019,
    "card_domestic": 0.02,
    "wallet": 0.02,
    "card_international": 0.03,
}
INSTANT_PREMIUM = 0.0025


def test_round_half_up_ties_round_up():
    assert round_half_up(2.5) == 3
    assert round_half_up(0.5) == 1
    assert round_half_up(1.4999999999) == 1
    assert round_half_up(1.5) == 2
    assert round_half_up(100) == 100


def test_rupees_to_paise():
    assert rupees_to_paise(1000) == 100_000
    assert rupees_to_paise(976.40) == 97_640
    assert rupees_to_paise(99.99) == 9_999


def test_worked_check_card_domestic_1000_rupees():
    # SS 3.2 worked check: Rs1000 domestic card -> fee 2000p, gst 360p, net 97,640p (Rs976.40)
    gross = rupees_to_paise(1000)
    fee = calc_fee_paise(gross, FEE_RATES["card_domestic"])
    gst = calc_gst_paise(fee)
    net = calc_net_paise(gross, fee, gst)
    assert fee == 2000
    assert gst == 360
    assert net == 97_640
    assert format_inr(net) == "₹976.40"


def test_fee_by_method():
    gross = 100_000  # Rs1000
    assert calc_fee_paise(gross, FEE_RATES["upi"]) == 0
    assert calc_fee_paise(gross, FEE_RATES["netbanking"]) == 1900
    assert calc_fee_paise(gross, FEE_RATES["wallet"]) == 2000
    assert calc_fee_paise(gross, FEE_RATES["card_international"]) == 3000


def test_instant_premium_additive():
    gross = 100_000
    rate = effective_fee_rate(FEE_RATES["card_domestic"], is_instant=True, instant_premium=INSTANT_PREMIUM)
    assert rate == 0.0225
    fee = calc_fee_paise(gross, rate)
    assert fee == 2250
    rate_not_instant = effective_fee_rate(FEE_RATES["card_domestic"], is_instant=False, instant_premium=INSTANT_PREMIUM)
    assert rate_not_instant == FEE_RATES["card_domestic"]


def test_gst_rate_default_18pct():
    assert calc_gst_paise(1000) == 180
    assert calc_gst_paise(2000) == 360


def test_within_tolerance_abs_and_rel():
    # tolerance: abs_paise=100, rel=0.001 -> min(100, round(0.001*expected))
    # expected=97_640 -> rel cap = round(97.64) = 98, which is the binding (smaller) cap
    assert within_tolerance(diff_paise=98, expected_paise=97_640, abs_paise=100, rel=0.001)
    assert not within_tolerance(diff_paise=99, expected_paise=97_640, abs_paise=100, rel=0.001)
    # large expected: rel cap (0.001 * 10_000_00 = 1000) exceeds abs cap 100, so abs wins
    assert within_tolerance(diff_paise=100, expected_paise=10_000_00, abs_paise=100, rel=0.001)
    assert not within_tolerance(diff_paise=150, expected_paise=10_000_00, abs_paise=100, rel=0.001)
    # small expected: rel cap (round(0.001*1000)=1) is smaller than abs cap 100
    assert within_tolerance(diff_paise=1, expected_paise=1000, abs_paise=100, rel=0.001)
    assert not within_tolerance(diff_paise=2, expected_paise=1000, abs_paise=100, rel=0.001)


def test_format_inr_indian_grouping():
    assert format_inr(97_640) == "₹976.40"
    assert format_inr(28_411_000) == "₹2,84,110.00"
    assert format_inr(0) == "₹0.00"
    assert format_inr(-5000) == "-₹50.00"
    assert format_inr(12345) == "₹123.45"
    assert format_inr(1_000_000_00) == "₹10,00,000.00"
