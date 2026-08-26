from engine.models import Exception_
from ai import explainer
from ai.explainer import _numerals_ok, explain_exception


def make_exc(**overrides):
    base = dict(
        exception_id="exc_0001",
        stage="C",
        reason_code="MISSING_IN_BANK",
        entities={"settlement_id": "setl_1", "utr": "UTR123"},
        expected={"credit_paise": 97640},
        actual={"credit_paise": None},
        amount_impact_paise=97640,
        tolerance_applied_paise=100,
        rule_trace=["C.utr_lookup:0 candidates"],
        is_reconcilable=False,
    )
    base.update(overrides)
    return Exception_(**base)


def test_numerals_ok_accepts_numbers_present_in_input():
    exc = make_exc()
    text = "The settlement expected ₹976.40 (97640 paise) but nothing arrived."
    assert _numerals_ok(text, exc)


def test_numerals_ok_rejects_invented_numeral():
    exc = make_exc()
    text = "The settlement is short by exactly ₹12,345.67, please investigate."
    assert not _numerals_ok(text, exc)


def test_explainer_falls_back_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    explainer._cache.clear()
    exc = make_exc()
    result = explain_exception(exc)
    assert result.model == "template-fallback"
    assert "976.40" in result.explanation


def test_explainer_result_is_cached(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    explainer._cache.clear()
    exc = make_exc(exception_id="exc_cache_test")
    first = explain_exception(exc)
    second = explain_exception(exc)
    assert first.cached is False
    assert second.cached is True
    assert second.explanation == first.explanation
