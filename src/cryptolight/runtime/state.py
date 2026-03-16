"""Shared runtime state for the application entrypoint."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Callable

market_snapshots: dict[str, dict] = {}
_market_snapshots_lock = threading.RLock()
active_symbols: list[str] = []


def update_market_snapshot(symbol: str, **fields) -> None:
    """Partially update the shared market snapshot for a symbol."""
    with _market_snapshots_lock:
        snapshot = dict(market_snapshots.get(symbol, {}))
        snapshot.update(fields)
        snapshot["updated_at"] = datetime.now().isoformat(timespec="seconds")
        market_snapshots[symbol] = snapshot


def get_market_snapshots_copy() -> dict[str, dict]:
    with _market_snapshots_lock:
        return {sym: dict(snap) for sym, snap in market_snapshots.items()}


def set_active_symbols(symbols: list[str]) -> None:
    active_symbols.clear()
    active_symbols.extend(symbols)


def get_runtime_state(
    settings: Any,
    *,
    get_effective_strategy_name: Callable[[Any], str],
) -> dict[str, Any]:
    symbols = list(active_symbols) if active_symbols else list(settings.symbol_list)
    return {
        "strategy_name": get_effective_strategy_name(settings),
        "trade_mode": settings.trade_mode,
        "symbol_list": symbols,
        "schedule_interval_minutes": settings.schedule_interval_minutes,
    }
