"""Glassmorphism 웹 대시보드 — FastAPI 앱 + API 엔드포인트"""

import logging
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger("cryptolight.web")

app = FastAPI(title="cryptolight dashboard", docs_url=None, redoc_url=None, openapi_url=None)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# HTTP Basic Auth
security = HTTPBasic(auto_error=False)


# 보안 헤더 미들웨어
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'"
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)

# CORS origin은 configure()에서 동적으로 설정
_cors_configured = False


@dataclass(frozen=True)
class WebSettings:
    """웹 레이어에 필요한 설정만 노출 (API 키 등 민감 정보 제외)."""
    strategy_name: str = "N/A"
    trade_mode: str = "N/A"
    symbol_list: tuple = field(default_factory=tuple)
    schedule_interval_minutes: int = 0
    username: str = ""
    password: str = ""


# main.py에서 주입하는 데이터 참조
_refs: dict = {}


def verify_credentials(credentials: HTTPBasicCredentials | None = Depends(security)):
    """HTTP Basic Auth 검증. username/password 미설정 시 경고 로그 후 통과."""
    ws: WebSettings = _refs.get("settings", WebSettings())
    if not ws.username or not ws.password:
        logger.warning("웹 대시보드 인증 미설정 — WEB_USERNAME/WEB_PASSWORD 환경변수를 설정하세요")
        return  # 인증 미설정 시 경고 후 통과 (로컬 개발용)
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="인증이 필요합니다",
            headers={"WWW-Authenticate": "Basic"},
        )
    user_ok = secrets.compare_digest(credentials.username.encode(), ws.username.encode())
    pass_ok = secrets.compare_digest(credentials.password.encode(), ws.password.encode())
    if not user_ok or not pass_ok:
        raise HTTPException(
            status_code=401,
            detail="잘못된 인증 정보입니다",
            headers={"WWW-Authenticate": "Basic"},
        )


def configure(
    market_snapshots: dict,
    broker=None,
    repo=None,
    health=None,
    settings=None,
):
    """main.py에서 호출하여 데이터 참조를 주입한다."""
    global _cors_configured
    _refs["market_snapshots"] = market_snapshots
    _refs["broker"] = broker
    _refs["repo"] = repo
    _refs["health"] = health
    # 민감 정보 제외하고 필요한 설정만 전달
    if settings:
        _refs["settings"] = WebSettings(
            strategy_name=settings.strategy_name,
            trade_mode=settings.trade_mode,
            symbol_list=tuple(settings.symbol_list),
            schedule_interval_minutes=settings.schedule_interval_minutes,
            username=getattr(settings, "web_username", ""),
            password=getattr(settings, "web_password", ""),
        )
        # CORS origin을 설정에서 동적으로 생성
        if not _cors_configured:
            host = getattr(settings, "web_host", "127.0.0.1")
            port = getattr(settings, "web_port", 8090)
            app.add_middleware(
                CORSMiddleware,
                allow_origins=[f"http://{host}:{port}"],
                allow_methods=["GET"],
                allow_credentials=True,
            )
            _cors_configured = True
    else:
        _refs["settings"] = WebSettings()
        if not _cors_configured:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=["http://127.0.0.1:8090"],
                allow_methods=["GET"],
                allow_credentials=True,
            )
            _cors_configured = True


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, _: None = Depends(verify_credentials)):
    settings = _refs.get("settings", WebSettings())
    return templates.TemplateResponse(request, "dashboard.html", {
        "strategy_name": settings.strategy_name,
        "trade_mode": settings.trade_mode,
    })


@app.get("/api/market")
async def api_market(_: None = Depends(verify_credentials)):
    snapshots = dict(_refs.get("market_snapshots", {}))  # shallow copy for thread safety
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
async def api_portfolio(_: None = Depends(verify_credentials)):
    broker = _refs.get("broker")
    snapshots = dict(_refs.get("market_snapshots", {}))  # shallow copy

    if broker is None:
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
async def api_trades(limit: int = Query(default=20, ge=1, le=100), _: None = Depends(verify_credentials)):
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
async def api_status(_: None = Depends(verify_credentials)):
    health = _refs.get("health")
    settings = _refs.get("settings", WebSettings())

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
        "strategy": settings.strategy_name,
        "trade_mode": settings.trade_mode,
        "symbols": list(settings.symbol_list),
        "interval_minutes": settings.schedule_interval_minutes,
        "health": health_data,
    }
