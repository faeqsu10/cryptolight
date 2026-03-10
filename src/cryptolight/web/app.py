"""Glassmorphism 웹 대시보드 — FastAPI 앱 + API 엔드포인트"""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger("cryptolight.web")

app = FastAPI(title="cryptolight dashboard", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# main.py에서 주입하는 데이터 참조
_refs: dict = {}


def configure(
    market_snapshots: dict,
    broker=None,
    repo=None,
    health=None,
    settings=None,
):
    """main.py에서 호출하여 데이터 참조를 주입한다."""
    _refs["market_snapshots"] = market_snapshots
    _refs["broker"] = broker
    _refs["repo"] = repo
    _refs["health"] = health
    _refs["settings"] = settings


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    settings = _refs.get("settings")
    return templates.TemplateResponse(request, "dashboard.html", {
        "strategy_name": settings.strategy_name if settings else "N/A",
        "trade_mode": settings.trade_mode if settings else "N/A",
    })


@app.get("/api/market")
async def api_market():
    snapshots = _refs.get("market_snapshots", {})
    result = {}
    for sym, snap in snapshots.items():
        result[sym] = {
            "price": snap.get("price", 0),
            "change": round(snap.get("change", 0), 2),
            "rsi": round(snap["rsi"], 1) if snap.get("rsi") is not None else None,
            "action": snap.get("action", "hold"),
            "regime": snap.get("regime", "N/A"),
            "adx": round(snap.get("adx", 0), 1),
        }
    return result


@app.get("/api/portfolio")
async def api_portfolio():
    from cryptolight.execution.paper_broker import PaperBroker

    broker = _refs.get("broker")
    snapshots = _refs.get("market_snapshots", {})

    if not isinstance(broker, PaperBroker):
        return {
            "cash": 0, "equity": 0, "pnl": 0, "pnl_pct": 0,
            "initial_balance": 0, "positions": [],
        }

    prices = {sym: snap["price"] for sym, snap in snapshots.items() if "price" in snap}
    info = broker.get_total_pnl(prices)

    positions = []
    for sym, pos_data in info["positions"].items():
        cur_price = prices.get(sym, 0)
        avg = pos_data["avg_price"]
        pnl = (cur_price - avg) * pos_data["qty"] if avg > 0 else 0
        pnl_pct = ((cur_price - avg) / avg * 100) if avg > 0 else 0
        positions.append({
            "symbol": sym,
            "quantity": pos_data["qty"],
            "avg_price": avg,
            "current_price": cur_price,
            "pnl": round(pnl),
            "pnl_pct": round(pnl_pct, 2),
        })

    return {
        "cash": round(info["cash"]),
        "equity": round(info["current_equity"]),
        "pnl": round(info["total_pnl"]),
        "pnl_pct": round(info["total_pnl_pct"], 2),
        "initial_balance": round(info["initial_balance"]),
        "positions": positions,
    }


@app.get("/api/trades")
async def api_trades(limit: int = 20):
    repo = _refs.get("repo")
    if not repo:
        return []

    trades = repo.get_trades(limit=limit)
    return [
        {
            "id": t.id,
            "symbol": t.symbol,
            "side": t.side,
            "price": t.price,
            "quantity": t.quantity,
            "amount_krw": round(t.amount_krw),
            "reason": t.reason,
            "timestamp": t.timestamp,
        }
        for t in trades
    ]


@app.get("/api/status")
async def api_status():
    health = _refs.get("health")
    settings = _refs.get("settings")

    health_data = {}
    if health:
        status = health.get_status()
        health_data = {
            "uptime_minutes": round(status.uptime_seconds / 60, 1),
            "total_cycles": status.total_cycles,
            "consecutive_errors": status.consecutive_errors,
            "healthy": health.is_healthy(),
        }

    return {
        "strategy": settings.strategy_name if settings else "N/A",
        "trade_mode": settings.trade_mode if settings else "N/A",
        "symbols": settings.symbol_list if settings else [],
        "interval_minutes": settings.schedule_interval_minutes if settings else 0,
        "health": health_data,
    }
