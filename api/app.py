"""COMPONENT 5 -- API (FastAPI). Endpoints per SS8."""
from __future__ import annotations

import csv
import io
import time

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ai.explainer import explain_exception
from api.store import RunState, store
from engine.reconcile import load_csvs, reconcile
from generator.config import load_config
from generator.generate import Generator
from metrics.compute import compute_metrics

app = FastAPI(title="LedgerLock API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG_PATH = "config.yaml"
PAGE_SIZE = 50


class GenerateRequest(BaseModel):
    seed: int | None = None
    n_orders: int | None = None


class AskRequest(BaseModel):
    question: str


def _require_run(run_id: str) -> RunState:
    state = store.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    return state


def _code(x) -> str:
    return str(x.value if hasattr(x, "value") else x)


@app.post("/generate")
def generate(req: GenerateRequest):
    cfg = load_config(CONFIG_PATH)
    seed = req.seed if req.seed is not None else cfg.seed
    n_orders = req.n_orders if req.n_orders is not None else cfg.n_orders

    state = store.create(seed=seed, n_orders=n_orders)
    gen = Generator(cfg, seed=seed, n_orders=n_orders)
    counts = gen.run(state.out_dir)
    state.counts = counts

    return {"run_id": state.run_id, "counts": counts}


@app.post("/reconcile/{run_id}")
def reconcile_run(run_id: str):
    state = _require_run(run_id)
    cfg = load_config(CONFIG_PATH)

    orders, recon_txns, bank_txns = load_csvs(
        state.out_dir / "orders.csv", state.out_dir / "razorpay_recon.csv", state.out_dir / "bank_statement.csv"
    )
    state.orders, state.recon_txns, state.bank_txns = orders, recon_txns, bank_txns
    state.index_sources()

    import json

    state.ground_truth = json.loads((state.out_dir / "ground_truth.json").read_text())["entities"]

    t0 = time.perf_counter()
    result = reconcile(
        orders,
        recon_txns,
        bank_txns,
        fee_rates=cfg.fee_rates,
        gst_rate=cfg.gst_rate,
        instant_premium=cfg.instant_premium,
        tol_abs=cfg.tolerance.abs_paise,
        tol_rel=cfg.tolerance.rel,
    )
    elapsed = time.perf_counter() - t0

    state.matches = result.matches
    state.exceptions = result.exceptions
    state.exceptions_by_id = {e.exception_id: e for e in result.exceptions}
    total_records = len(orders) + len(recon_txns) + len(bank_txns)
    state.metrics = compute_metrics(result, state.ground_truth, elapsed_seconds=elapsed, total_records=total_records)
    state.reconciled = True

    summary = {
        "auto_match_rate": state.metrics["auto_match_rate"],
        "matched_count": state.metrics["matched_count"],
        "exception_count": len(result.exceptions),
        "false_match_count": state.metrics["false_match_count"],
        "value_reconciled_paise": state.metrics["value_reconciled_paise"],
        "value_flagged_paise": state.metrics["value_flagged_paise"],
        "stage_counts": result.stage_counts,
    }
    return {"metrics": state.metrics, "summary": summary}


@app.get("/runs/{run_id}/metrics")
def get_metrics(run_id: str):
    state = _require_run(run_id)
    if not state.reconciled:
        raise HTTPException(status_code=409, detail="run has not been reconciled yet")
    return state.metrics


@app.get("/runs/{run_id}/matches")
def get_matches(run_id: str, stage: str | None = None, page: int = Query(1, ge=1)):
    state = _require_run(run_id)
    items = state.matches
    if stage:
        items = [m for m in items if m.stage == stage]
    start = (page - 1) * PAGE_SIZE
    page_items = items[start : start + PAGE_SIZE]
    return {
        "page": page,
        "page_size": PAGE_SIZE,
        "total": len(items),
        "items": [
            {"stage": m.stage, "entity_id": m.entity_id, "reason_code": _code(m.reason_code), "tags": [_code(t) for t in m.tags], "details": m.details}
            for m in page_items
        ],
    }


@app.get("/runs/{run_id}/exceptions")
def get_exceptions(run_id: str, reason: str | None = None, page: int = Query(1, ge=1)):
    state = _require_run(run_id)
    items = state.exceptions
    if reason:
        items = [e for e in items if _code(e.reason_code) == reason]
    start = (page - 1) * PAGE_SIZE
    page_items = items[start : start + PAGE_SIZE]
    return {"page": page, "page_size": PAGE_SIZE, "total": len(items), "items": [e.model_dump() for e in page_items]}


def _gather_source_rows(state: RunState, entities: dict) -> dict:
    order_row = None
    if entities.get("order_id"):
        o = state.orders_by_id.get(entities["order_id"])
        order_row = o.model_dump() if o else None

    recon_rows: list[dict] = []
    for key in ("payment_id", "refund_id", "adjustment_id"):
        val = entities.get(key)
        if val and val in state.recon_by_entity_id:
            recon_rows.append(state.recon_by_entity_id[val].model_dump())
    if entities.get("settlement_id"):
        for t in state.recon_by_settlement.get(entities["settlement_id"], []):
            row = t.model_dump()
            if row not in recon_rows:
                recon_rows.append(row)

    bank_rows: list[dict] = []
    if entities.get("utr"):
        bank_rows.extend(b.model_dump() for b in state.bank_by_utr.get(entities["utr"], []))
    if entities.get("bank_ref_no") and entities["bank_ref_no"] in state.bank_by_ref:
        row = state.bank_by_ref[entities["bank_ref_no"]].model_dump()
        if row not in bank_rows:
            bank_rows.append(row)

    return {"order": order_row, "recon_rows": recon_rows, "bank_rows": bank_rows}


@app.get("/runs/{run_id}/exceptions/{exception_id}")
def get_exception_detail(run_id: str, exception_id: str):
    state = _require_run(run_id)
    exc = state.exceptions_by_id.get(exception_id)
    if exc is None:
        raise HTTPException(status_code=404, detail=f"exception {exception_id!r} not found")
    return {**exc.model_dump(), "source_rows": _gather_source_rows(state, exc.entities)}


@app.post("/runs/{run_id}/explain/{exception_id}")
def explain(run_id: str, exception_id: str):
    state = _require_run(run_id)
    exc = state.exceptions_by_id.get(exception_id)
    if exc is None:
        raise HTTPException(status_code=404, detail=f"exception {exception_id!r} not found")
    ai_result = explain_exception(exc)
    exc.ai = ai_result
    return exc.model_dump()


@app.post("/runs/{run_id}/ask")
def ask(run_id: str, req: AskRequest):
    # Stretch goal (SS7.3) -- not implemented for this build.
    raise HTTPException(status_code=501, detail="Q&A agent is a stretch goal and is not implemented")


@app.get("/runs/{run_id}/export.csv")
def export_csv(run_id: str):
    state = _require_run(run_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["exception_id", "stage", "reason_code", "amount_impact_paise", "is_reconcilable", "entities", "expected", "actual", "ai_explanation", "ai_suggested_action"])
    for e in state.exceptions:
        writer.writerow(
            [
                e.exception_id,
                e.stage,
                _code(e.reason_code),
                e.amount_impact_paise,
                e.is_reconcilable,
                e.entities,
                e.expected,
                e.actual,
                e.ai.explanation if e.ai else "",
                e.ai.suggested_action if e.ai else "",
            ]
        )
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=ledgerlock_{run_id}_exceptions.csv"},
    )
