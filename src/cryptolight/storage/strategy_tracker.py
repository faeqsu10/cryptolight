"""전략 성과 추적 — 전략별 승률, 수익률, 거래 수 집계"""

import logging

from cryptolight.storage.repository import TradeRepository

logger = logging.getLogger("cryptolight.storage.strategy_tracker")


class StrategyTracker:
    """전략별 성과를 DB에서 집계한다."""

    def __init__(self, repo: TradeRepository):
        self._repo = repo

    def get_strategy_stats(self) -> list[dict]:
        """전략별 성과 통계를 반환한다."""
        rows = self._repo._conn.execute("""
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

        stats = []
        for row in rows:
            strategy = row["strategy"]
            bought = row["total_bought"]
            sold = row["total_sold"]
            commission = row["total_commission"]
            pnl = sold - bought - commission

            stats.append({
                "strategy": strategy,
                "trade_count": row["trade_count"],
                "total_bought": round(bought, 0),
                "total_sold": round(sold, 0),
                "total_commission": round(commission, 0),
                "realized_pnl": round(pnl, 0),
            })

        return stats

    def get_strategy_win_rate(self, strategy: str) -> dict:
        """특정 전략의 승률을 계산한다 (매도 건 기준)."""
        sells = self._repo._conn.execute("""
            SELECT t1.price as sell_price, t2.price as buy_price
            FROM trades t1
            LEFT JOIN trades t2 ON t1.symbol = t2.symbol
                AND t2.side = 'buy'
                AND t2.id < t1.id
                AND t2.strategy = t1.strategy
            WHERE t1.side = 'sell' AND t1.strategy = ?
            ORDER BY t1.id
        """, (strategy,)).fetchall()

        wins = sum(1 for s in sells if s["sell_price"] and s["buy_price"] and s["sell_price"] > s["buy_price"])
        total = len(sells)

        return {
            "strategy": strategy,
            "total_sells": total,
            "wins": wins,
            "win_rate": round(wins / total * 100, 1) if total > 0 else 0.0,
        }

    def summary_text(self) -> str:
        """전략별 성과 요약 텍스트."""
        stats = self.get_strategy_stats()
        if not stats:
            return "전략별 거래 데이터 없음"

        lines = ["=== 전략별 성과 ==="]
        for s in stats:
            lines.append(
                f"  {s['strategy']}: {s['trade_count']}건, "
                f"손익 {s['realized_pnl']:+,.0f} KRW"
            )
        return "\n".join(lines)
