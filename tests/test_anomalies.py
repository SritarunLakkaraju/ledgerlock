"""For each injected_anomaly the generator writes to ground_truth.json, the
engine must assign that entity the expected_reason_code (SS10)."""
import pytest

from engine.reconcile import load_csvs, reconcile
from generator.config import load_config
from generator.generate import Generator
from metrics.compute import _build_entity_verdicts

ALL_ANOMALY_TYPES = [
    "orphan_order",
    "partial_refund_same_settlement",
    "partial_refund_later_settlement",
    "full_refund_later_settlement",
    "multi_day_settlement",
    "rounding_drift",
    "duplicate_utr",
    "missing_in_bank",
    "missing_in_settlement",
    "adjustment",
    "fee_variance_instant",
]


@pytest.fixture(scope="module")
def golden_run(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("anomaly_run")
    cfg = load_config("config.yaml")
    gen = Generator(cfg, seed=42)
    gen.run(tmp_path)
    orders, recon, bank = load_csvs(tmp_path / "orders.csv", tmp_path / "razorpay_recon.csv", tmp_path / "bank_statement.csv")
    result = reconcile(
        orders,
        recon,
        bank,
        fee_rates=cfg.fee_rates,
        gst_rate=cfg.gst_rate,
        instant_premium=cfg.instant_premium,
        tol_abs=cfg.tolerance.abs_paise,
        tol_rel=cfg.tolerance.rel,
    )
    import json

    gt = json.loads((tmp_path / "ground_truth.json").read_text())["entities"]
    verdicts = _build_entity_verdicts(result)
    return gt, verdicts


def test_all_11_anomaly_types_present(golden_run):
    gt, _ = golden_run
    present = {e["injected_anomaly"] for e in gt if e["injected_anomaly"]}
    assert present == set(ALL_ANOMALY_TYPES)


@pytest.mark.parametrize("anomaly", ALL_ANOMALY_TYPES)
def test_anomaly_gets_expected_reason_code(golden_run, anomaly):
    gt, verdicts = golden_run
    rows = [e for e in gt if e["injected_anomaly"] == anomaly]
    assert rows, f"no ground-truth rows found for anomaly type {anomaly!r}"
    for row in rows:
        v = verdicts.get(row["entity_id"])
        if v is None and row.get("true_bank_utr"):
            v = verdicts.get(row["true_bank_utr"])
        codes = v["reason_codes"] if v else set()
        assert row["expected_reason_code"] in codes, (
            f"{anomaly}: entity {row['entity_id']} expected {row['expected_reason_code']!r}, engine produced {codes}"
        )
