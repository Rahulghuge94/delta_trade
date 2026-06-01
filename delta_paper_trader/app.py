from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from delta_paper_trader.backtest import run_backtest
from delta_paper_trader.engine import PaperTradingEngine
from delta_paper_trader.strategy import strategy_catalog

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

engine = PaperTradingEngine()
app = FastAPI(title="Delta Paper Momentum Trader")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/strategy-catalog")
async def get_strategy_catalog() -> list[dict[str, Any]]:
    return strategy_catalog()


@app.get("/api/status")
async def status() -> dict[str, Any]:
    return engine.snapshot()


@app.post("/api/engine/start")
async def start_engine(payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    payload = payload or {}
    try:
        await engine.start(payload.get("symbols"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return engine.snapshot()


@app.post("/api/engine/stop")
async def stop_engine() -> dict[str, Any]:
    await engine.stop()
    return engine.snapshot()


@app.post("/api/strategies")
async def create_strategy(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        config = engine.add_strategy(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"strategy": config.id, "status": engine.snapshot()}


@app.patch("/api/strategies/{strategy_id}")
async def update_strategy(strategy_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if strategy_id not in engine.configs:
        raise HTTPException(status_code=404, detail="Strategy not found")
    try:
        await engine.update_strategy(strategy_id, payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return engine.snapshot()


@app.delete("/api/strategies/{strategy_id}")
async def delete_strategy(strategy_id: str) -> dict[str, Any]:
    await engine.delete_strategy(strategy_id)
    return engine.snapshot()


@app.post("/api/backtest")
async def backtest(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return run_backtest(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
