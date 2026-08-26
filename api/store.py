"""In-memory run state (SS8: "Run state in-memory dict (or SQLite)"). A
buildathon demo doesn't need persistence across process restarts -- each
`/generate` call creates a fresh run_id the frontend carries through the
rest of the flow."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from engine.models import BankTxn, Exception_, MatchRecord, Order, ReconTxn

RUNS_DIR = Path("runs")


@dataclass
class RunState:
    run_id: str
    seed: int
    n_orders: int
    out_dir: Path
    counts: dict = field(default_factory=dict)

    orders: list[Order] = field(default_factory=list)
    recon_txns: list[ReconTxn] = field(default_factory=list)
    bank_txns: list[BankTxn] = field(default_factory=list)
    ground_truth: list[dict] = field(default_factory=list)

    matches: list[MatchRecord] = field(default_factory=list)
    exceptions: list[Exception_] = field(default_factory=list)
    exceptions_by_id: dict[str, Exception_] = field(default_factory=dict)
    metrics: Optional[dict] = None
    reconciled: bool = False

    orders_by_id: dict[str, Order] = field(default_factory=dict)
    recon_by_entity_id: dict[str, ReconTxn] = field(default_factory=dict)
    recon_by_settlement: dict[str, list[ReconTxn]] = field(default_factory=dict)
    bank_by_utr: dict[str, list[BankTxn]] = field(default_factory=dict)
    bank_by_ref: dict[str, BankTxn] = field(default_factory=dict)

    def index_sources(self):
        self.orders_by_id = {o.order_id: o for o in self.orders}
        self.recon_by_entity_id = {t.entity_id: t for t in self.recon_txns}
        self.recon_by_settlement = {}
        for t in self.recon_txns:
            self.recon_by_settlement.setdefault(t.settlement_id, []).append(t)
        self.bank_by_utr = {}
        for b in self.bank_txns:
            self.bank_by_utr.setdefault(b.utr, []).append(b)
        self.bank_by_ref = {b.bank_ref_no: b for b in self.bank_txns}


class RunStore:
    def __init__(self):
        self._runs: dict[str, RunState] = {}

    def create(self, seed: int, n_orders: int) -> RunState:
        run_id = uuid.uuid4().hex[:10]
        out_dir = RUNS_DIR / run_id
        state = RunState(run_id=run_id, seed=seed, n_orders=n_orders, out_dir=out_dir)
        self._runs[run_id] = state
        return state

    def get(self, run_id: str) -> Optional[RunState]:
        return self._runs.get(run_id)


store = RunStore()
