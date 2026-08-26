"""Seed 42 -> byte-identical data (SS4.3/P6) -> exact, pinned metrics (SS10).
If this test's numbers ever need to change, it means a deliberate behavior
change was made to the generator or engine -- re-pin deliberately, don't
"fix" the test to make it pass."""
from engine.reconcile import load_csvs, reconcile
from generator.config import load_config
from generator.generate import Generator
from metrics.compute import compute_metrics


def _run(tmp_path, seed=42):
    cfg = load_config("config.yaml")
    gen = Generator(cfg, seed=seed)
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
    metrics = compute_metrics(result, gt)
    return result, gt, metrics


def test_seed_42_reproducible_files(tmp_path):
    cfg = load_config("config.yaml")
    Generator(cfg, seed=42).run(tmp_path / "run1")
    Generator(cfg, seed=42).run(tmp_path / "run2")
    for fname in ("orders.csv", "razorpay_recon.csv", "bank_statement.csv", "ground_truth.json"):
        assert (tmp_path / "run1" / fname).read_bytes() == (tmp_path / "run2" / fname).read_bytes()


def test_golden_metrics_seed_42(tmp_path):
    result, gt, metrics = _run(tmp_path, seed=42)

    assert len(gt) == 363
    assert metrics["false_match_count"] == 0
    assert metrics["reason_code_accuracy"] == 1.0
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["auto_match_rate"] == 0.9669
    assert metrics["total_entities_evaluated"] == 363
    assert metrics["matched_count"] == 351


def test_definition_of_done_anomaly_coverage(tmp_path):
    """definition of done: >=8 anomaly types, each caught with the correct reason code."""
    result, gt, metrics = _run(tmp_path, seed=42)
    anomaly_types = {e["injected_anomaly"] for e in gt if e["injected_anomaly"]}
    assert len(anomaly_types) >= 8
    assert metrics["reason_code_accuracy"] == 1.0
