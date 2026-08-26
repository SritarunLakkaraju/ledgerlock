"""Used by `make demo`: generate -> reconcile -> print the headline numbers
to the terminal before the API/UI servers come up, so the honest numbers are
visible even if you never open a browser."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.money import format_inr  # noqa: E402
from engine.reconcile import load_csvs, reconcile  # noqa: E402
from generator.config import load_config  # noqa: E402
from generator.generate import Generator  # noqa: E402
from metrics.compute import compute_metrics  # noqa: E402

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 42
OUT_DIR = Path("runs") / "demo"

cfg = load_config("config.yaml")
gen = Generator(cfg, seed=SEED)
counts = gen.run(OUT_DIR)

orders, recon, bank = load_csvs(OUT_DIR / "orders.csv", OUT_DIR / "razorpay_recon.csv", OUT_DIR / "bank_statement.csv")

t0 = time.perf_counter()
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
elapsed = time.perf_counter() - t0

gt = json.loads((OUT_DIR / "ground_truth.json").read_text())["entities"]
total_records = len(orders) + len(recon) + len(bank)
metrics = compute_metrics(result, gt, elapsed_seconds=elapsed, total_records=total_records)

print(f"\nLedgerLock -- seed {SEED}")
print(f"  {counts['orders']} orders, {counts['settlements']} settlements, {counts['bank_rows']} bank rows")
print(
    f"  {metrics['auto_match_rate'] * 100:.1f}% auto-matched · {len(result.exceptions)} flagged · "
    f"{metrics['false_match_count']} false matches"
)
print(f"  {format_inr(metrics['value_reconciled_paise'])} reconciled / {format_inr(metrics['value_flagged_paise'])} flagged")
print(f"  reason-code accuracy: {metrics['reason_code_accuracy'] * 100:.1f}%")
print(f"  data written to {OUT_DIR}/\n")
