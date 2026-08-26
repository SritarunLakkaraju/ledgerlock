from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class ToleranceConfig(BaseModel):
    abs_paise: int
    rel: float


class AnomalyRates(BaseModel):
    partial_refund_same_settlement: float
    partial_refund_later_settlement: float
    full_refund_later_settlement: float
    multi_day_settlement: float
    rounding_drift: float
    duplicate_utr: float
    missing_in_bank: float
    missing_in_settlement: float
    orphan_order: float
    adjustment: float
    fee_variance_instant: float


class GeneratorConfig(BaseModel):
    seed: int
    n_orders: int
    settlement_cycle_days: int
    gst_rate: float
    fee_rates: dict[str, float]
    instant_premium: float
    tolerance: ToleranceConfig
    anomaly_rates: AnomalyRates


def load_config(path: str | Path = "config.yaml") -> GeneratorConfig:
    with open(path) as f:
        raw = yaml.safe_load(f)
    return GeneratorConfig(**raw)
