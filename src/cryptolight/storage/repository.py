import logging
import sqlite3
from pathlib import Path

from cryptolight.storage.models import TradeRecord

logger = logging.getLogger("cryptolight.storage")

DEFAULT_DB_PATH = Path("data/trades.db")


class TradeRepository:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
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
                timestamp TEXT NOT NULL
            )
        """)
        self._conn.commit()

    def save_trade(self, trade: TradeRecord) -> int:
        cursor = self._conn.execute(
            """INSERT INTO trades (symbol, side, price, quantity, amount_krw, commission, reason, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (trade.symbol, trade.side, trade.price, trade.quantity,
             trade.amount_krw, trade.commission, trade.reason, trade.timestamp),
        )
        self._conn.commit()
        logger.info("거래 기록 저장: %s %s %.8f @ %s", trade.side, trade.symbol, trade.quantity, f"{trade.price:,.0f}")
        return cursor.lastrowid

    def get_trades(self, symbol: str | None = None, limit: int = 50) -> list[TradeRecord]:
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
            from datetime import datetime
            date = datetime.now().strftime("%Y-%m-%d")

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

        return {
            "date": date,
            "realized_pnl": total_sold - total_bought - total_commission,
            "total_bought": total_bought,
            "total_sold": total_sold,
            "total_commission": total_commission,
            "trade_count": trade_count,
        }

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
