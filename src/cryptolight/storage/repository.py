import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from cryptolight.storage.models import TradeRecord

logger = logging.getLogger("cryptolight.storage")

DEFAULT_DB_PATH = Path("data/trades.db")


class TradeRepository:
    def __init__(self, db_path: Path | None = None):
        if db_path is None:
            db_path = DEFAULT_DB_PATH
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._create_tables()

    def _create_tables(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                quantity REAL NOT NULL,
                amount_krw REAL NOT NULL,
                commission REAL NOT NULL,
                reason TEXT,
                strategy TEXT DEFAULT '',
                timestamp TEXT NOT NULL
            )
        """)
        # 기존 테이블에 strategy 컬럼이 없으면 추가
        try:
            self._conn.execute("SELECT strategy FROM trades LIMIT 1")
        except Exception:
            self._conn.execute("ALTER TABLE trades ADD COLUMN strategy TEXT DEFAULT ''")
            self._conn.commit()
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                quantity REAL NOT NULL,
                avg_price REAL NOT NULL,
                total_cost REAL NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_state (
                key TEXT PRIMARY KEY,
                value REAL NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS strategy_switches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_strategy TEXT NOT NULL,
                to_strategy TEXT NOT NULL,
                reason TEXT,
                switched_at TEXT NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS strategy_parameter_state (
                strategy TEXT NOT NULL,
                parameter TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (strategy, parameter)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS parameter_adjustments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy TEXT NOT NULL,
                parameter TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT NOT NULL,
                reason TEXT,
                explanation TEXT DEFAULT '',
                metric_summary TEXT DEFAULT '',
                applied_at TEXT NOT NULL
            )
        """)
        self._conn.commit()

    def save_trade(self, trade: TradeRecord) -> int:
        with self._lock:
            cursor = self._conn.execute(
                """INSERT INTO trades (symbol, side, price, quantity, amount_krw, commission, reason, strategy, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (trade.symbol, trade.side, trade.price, trade.quantity,
                 trade.amount_krw, trade.commission, trade.reason, trade.strategy, trade.timestamp),
            )
            self._conn.commit()
        logger.info("거래 기록 저장: %s %s %.8f @ %s", trade.side, trade.symbol, trade.quantity, f"{trade.price:,.0f}")
        return cursor.lastrowid

    def get_trades(self, symbol: str | None = None, limit: int = 50) -> list[TradeRecord]:
        with self._lock:
            if symbol:
                rows = self._conn.execute(
                    "SELECT * FROM trades WHERE symbol = ? ORDER BY id DESC LIMIT ?",
                    (symbol, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [TradeRecord(**dict(row)) for row in rows]

    def get_daily_pnl(self, date: str | None = None) -> dict:
        """일일 실현 손익 계산. date 형식: YYYY-MM-DD"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM trades WHERE timestamp LIKE ? ORDER BY id",
                (f"{date}%",),
            ).fetchall()

        total_bought = 0.0
        total_sold = 0.0
        total_commission = 0.0
        trade_count = 0

        for row in rows:
            trade_count += 1
            total_commission += row["commission"]
            if row["side"] == "buy":
                total_bought += row["amount_krw"]
            else:
                total_sold += row["amount_krw"]

        # 매도가 있을 때만 실현 손익 계산 (매수만 있는 날은 아직 미실현)
        if total_sold > 0:
            realized_pnl = total_sold - total_bought - total_commission
        else:
            realized_pnl = -total_commission  # 수수료만 차감

        return {
            "date": date,
            "realized_pnl": realized_pnl,
            "total_bought": total_bought,
            "total_sold": total_sold,
            "total_commission": total_commission,
            "trade_count": trade_count,
        }

    def save_positions(self, positions: dict, balance_krw: float) -> None:
        """포지션과 잔고를 DB에 저장한다."""
        with self._lock:
            self._conn.execute("DELETE FROM positions")
            for symbol, pos in positions.items():
                self._conn.execute(
                    "REPLACE INTO positions (symbol, quantity, avg_price, total_cost) VALUES (?, ?, ?, ?)",
                    (symbol, pos.quantity, pos.avg_price, pos.total_cost),
                )
            self._conn.execute(
                "REPLACE INTO paper_state (key, value) VALUES (?, ?)",
                ("balance_krw", balance_krw),
            )
            self._conn.commit()
        logger.debug("포지션 저장 완료: %d개 종목, 잔고 %s", len(positions), f"{balance_krw:,.0f}")

    def load_positions(self) -> tuple[dict, float | None]:
        """DB에서 포지션과 잔고를 로드한다. 없으면 ({}, None) 반환."""
        with self._lock:
            rows = self._conn.execute("SELECT symbol, quantity, avg_price, total_cost FROM positions").fetchall()
            balance_row = self._conn.execute(
                "SELECT value FROM paper_state WHERE key = ?", ("balance_krw",)
            ).fetchone()
        positions: dict = {}
        for row in rows:
            positions[row["symbol"]] = {
                "symbol": row["symbol"],
                "quantity": row["quantity"],
                "avg_price": row["avg_price"],
                "total_cost": row["total_cost"],
            }
        balance_krw = balance_row["value"] if balance_row else None

        return positions, balance_krw

    def get_strategy_aggregates(self) -> list[dict]:
        """전략별 집계 통계를 반환한다."""
        with self._lock:
            rows = self._conn.execute("""
                SELECT
                    strategy,
                    COUNT(*) as trade_count,
                    SUM(CASE WHEN side='buy' THEN amount_krw ELSE 0 END) as total_bought,
                    SUM(CASE WHEN side='sell' THEN amount_krw ELSE 0 END) as total_sold,
                    SUM(commission) as total_commission
                FROM trades
                WHERE strategy != '' AND strategy IS NOT NULL
                GROUP BY strategy
                ORDER BY trade_count DESC
            """).fetchall()
        return [dict(row) for row in rows]

    def get_strategy_sell_pairs(self, strategy: str) -> list[dict]:
        """특정 전략의 매도 건별 직전 매수 가격을 반환한다."""
        with self._lock:
            rows = self._conn.execute("""
                SELECT t1.price as sell_price,
                       (SELECT t2.price FROM trades t2
                        WHERE t2.symbol = t1.symbol
                          AND t2.side = 'buy'
                          AND t2.id < t1.id
                          AND t2.strategy = t1.strategy
                        ORDER BY t2.id DESC LIMIT 1) as buy_price
                FROM trades t1
                WHERE t1.side = 'sell' AND t1.strategy = ?
                ORDER BY t1.id
            """, (strategy,)).fetchall()
        return [dict(row) for row in rows]

    def get_strategy_trades(self, strategy: str, since: str = "") -> list[dict]:
        """특정 전략의 거래 내역을 반환한다. since: YYYY-MM-DD 이후."""
        with self._lock:
            if since:
                rows = self._conn.execute(
                    "SELECT * FROM trades WHERE strategy = ? AND timestamp >= ? ORDER BY id",
                    (strategy, since),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM trades WHERE strategy = ? ORDER BY id",
                    (strategy,),
                ).fetchall()
        return [dict(row) for row in rows]

    def record_strategy_switch(
        self, from_strategy: str, to_strategy: str, reason: str
    ) -> None:
        """전략 전환을 기록한다."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO strategy_switches (from_strategy, to_strategy, reason, switched_at) VALUES (?, ?, ?, ?)",
                (from_strategy, to_strategy, reason, datetime.now().isoformat()),
            )
            self._conn.commit()

    def get_strategy_switches(self, limit: int = 10) -> list[dict]:
        """최근 전략 전환 이력을 반환한다."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM strategy_switches ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_strategy_parameters(self, strategy: str) -> dict:
        """전략별 현재 적용 파라미터를 반환한다."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT parameter, value FROM strategy_parameter_state WHERE strategy = ?",
                (strategy,),
            ).fetchall()
        return {
            row["parameter"]: json.loads(row["value"])
            for row in rows
        }

    def apply_parameter_adjustments(
        self,
        strategy: str,
        new_params: dict,
        reason: str,
        metric_summary: str = "",
        explanations: dict[str, str] | None = None,
        previous_params: dict | None = None,
    ) -> list[dict]:
        """전략 파라미터 변경을 기록하고 현재 상태를 갱신한다."""
        explanations = explanations or {}
        current_params = previous_params or self.get_strategy_parameters(strategy)
        applied_at = datetime.now().isoformat()
        changed: list[dict] = []

        with self._lock:
            for parameter, new_value in new_params.items():
                old_value = current_params.get(parameter)
                if old_value == new_value:
                    continue

                self._conn.execute(
                    """
                    INSERT INTO parameter_adjustments
                    (strategy, parameter, old_value, new_value, reason, explanation, metric_summary, applied_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        strategy,
                        parameter,
                        json.dumps(old_value, ensure_ascii=False) if old_value is not None else None,
                        json.dumps(new_value, ensure_ascii=False),
                        reason,
                        explanations.get(parameter, ""),
                        metric_summary,
                        applied_at,
                    ),
                )
                self._conn.execute(
                    """
                    REPLACE INTO strategy_parameter_state (strategy, parameter, value, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (strategy, parameter, json.dumps(new_value, ensure_ascii=False), applied_at),
                )
                changed.append({
                    "strategy": strategy,
                    "parameter": parameter,
                    "old_value": old_value,
                    "new_value": new_value,
                    "reason": reason,
                    "explanation": explanations.get(parameter, ""),
                    "metric_summary": metric_summary,
                    "applied_at": applied_at,
                })

            self._conn.commit()

        return changed

    def get_recent_parameter_adjustments(
        self,
        limit: int = 10,
        strategy: str | None = None,
    ) -> list[dict]:
        """최근 파라미터 조정 이력을 반환한다."""
        with self._lock:
            if strategy:
                rows = self._conn.execute(
                    """
                    SELECT * FROM parameter_adjustments
                    WHERE strategy = ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (strategy, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM parameter_adjustments ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()

        result = []
        for row in rows:
            item = dict(row)
            item["old_value"] = json.loads(item["old_value"]) if item["old_value"] else None
            item["new_value"] = json.loads(item["new_value"])
            result.append(item)
        return result

    def get_latest_parameter_adjustment(self, strategy: str) -> dict | None:
        """특정 전략의 가장 최근 파라미터 조정 1건을 반환한다."""
        rows = self.get_recent_parameter_adjustments(limit=1, strategy=strategy)
        return rows[0] if rows else None

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
