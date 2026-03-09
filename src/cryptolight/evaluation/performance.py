"""성과 평가기 — 전략별 Sharpe, 승률, MDD 등 핵심 메트릭 계산"""

import logging
import statistics
from datetime import datetime, timedelta

from cryptolight.storage.repository import TradeRepository

logger = logging.getLogger("cryptolight.evaluation.performance")

MIN_TRADES_FOR_EVALUATION = 10


class PerformanceEvaluator:
    """DB 거래 기록에서 전략별 성과 메트릭을 계산한다."""

    def __init__(self, repo: TradeRepository):
        self._repo = repo

    def evaluate_strategy(self, strategy: str, days: int = 30) -> dict:
        """특정 전략의 최근 N일 성과를 평가한다."""
        trades = self._get_recent_trades(strategy, days)

        if len(trades) < MIN_TRADES_FOR_EVALUATION:
            return {
                "strategy": strategy,
                "status": "insufficient_data",
                "trade_count": len(trades),
                "message": f"최소 {MIN_TRADES_FOR_EVALUATION}건 필요 (현재 {len(trades)}건)",
            }

        daily_returns = self._calc_daily_returns(trades)
        win_rate = self._calc_win_rate(trades)
        total_return = self._calc_total_return(trades)
        max_dd = self._calc_max_drawdown(trades)
        sharpe = self._calc_sharpe(daily_returns)

        return {
            "strategy": strategy,
            "status": "evaluated",
            "trade_count": len(trades),
            "win_rate": round(win_rate, 2),
            "total_return_pct": round(total_return, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 3),
            "daily_returns": daily_returns,
        }

    def evaluate_all(self, days: int = 30) -> list[dict]:
        """모든 전략의 성과를 평가한다."""
        strategies = self._get_active_strategies()
        results = []
        for strategy in strategies:
            result = self.evaluate_strategy(strategy, days)
            results.append(result)
        results.sort(key=lambda x: x.get("sharpe_ratio", -999), reverse=True)
        return results

    def summary_text(self, days: int = 30) -> str:
        """성과 평가 요약 텍스트."""
        results = self.evaluate_all(days)
        if not results:
            return "평가 가능한 전략 없음"

        lines = [f"=== 전략 성과 평가 (최근 {days}일) ==="]
        for r in results:
            if r["status"] == "insufficient_data":
                lines.append(f"  {r['strategy']}: 데이터 부족 ({r['trade_count']}건)")
            else:
                lines.append(
                    f"  {r['strategy']}: Sharpe={r['sharpe_ratio']:.3f}, "
                    f"승률={r['win_rate']:.0f}%, 수익={r['total_return_pct']:+.1f}%, "
                    f"MDD={r['max_drawdown_pct']:.1f}%, 거래={r['trade_count']}건"
                )
        return "\n".join(lines)

    def _get_active_strategies(self) -> list[str]:
        """DB에서 사용된 전략 목록을 가져온다."""
        rows = self._repo.get_strategy_aggregates()
        return [row["strategy"] for row in rows if row["strategy"]]

    def _get_recent_trades(self, strategy: str, days: int) -> list[dict]:
        """최근 N일 내의 특정 전략 거래를 가져온다."""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        all_trades = self._repo.get_strategy_trades(strategy, since=cutoff)
        return all_trades

    def _calc_win_rate(self, trades: list[dict]) -> float:
        """승률 계산 (매도 건 중 수익 비율)."""
        sells = [t for t in trades if t["side"] == "sell"]
        if not sells:
            return 0.0
        # 각 매도 직전 매수와 비교
        wins = 0
        for i, trade in enumerate(trades):
            if trade["side"] == "sell":
                # 직전 매수 찾기
                for j in range(i - 1, -1, -1):
                    if trades[j]["side"] == "buy" and trades[j]["symbol"] == trade["symbol"]:
                        if trade["price"] > trades[j]["price"]:
                            wins += 1
                        break
        return (wins / len(sells)) * 100 if sells else 0.0

    def _calc_total_return(self, trades: list[dict]) -> float:
        """총 수익률 계산."""
        total_bought = sum(t["amount_krw"] for t in trades if t["side"] == "buy")
        total_sold = sum(t["amount_krw"] for t in trades if t["side"] == "sell")
        total_commission = sum(t["commission"] for t in trades)
        if total_bought == 0:
            return 0.0
        return ((total_sold - total_bought - total_commission) / total_bought) * 100

    def _calc_daily_returns(self, trades: list[dict]) -> list[float]:
        """일별 수익률 리스트를 계산한다."""
        if not trades:
            return []
        # 날짜별 손익 집계
        daily_pnl: dict[str, float] = {}
        daily_invested: dict[str, float] = {}
        for t in trades:
            day = t["timestamp"][:10]
            if day not in daily_pnl:
                daily_pnl[day] = 0.0
                daily_invested[day] = 0.0
            if t["side"] == "buy":
                daily_invested[day] += t["amount_krw"]
                daily_pnl[day] -= t["amount_krw"] + t["commission"]
            else:
                daily_pnl[day] += t["amount_krw"] - t["commission"]

        returns = []
        for day in sorted(daily_pnl.keys()):
            invested = daily_invested.get(day, 0)
            if invested > 0:
                returns.append(daily_pnl[day] / invested)
            elif daily_pnl[day] != 0:
                returns.append(daily_pnl[day] / 100000)  # 기본 단위
        return returns

    def _calc_sharpe(self, daily_returns: list[float], risk_free: float = 0.0) -> float:
        """Sharpe Ratio 계산 (연율화)."""
        if len(daily_returns) < 2:
            return 0.0
        mean_r = statistics.mean(daily_returns)
        std_r = statistics.stdev(daily_returns)
        if std_r == 0:
            return 0.0
        # 연율화: sqrt(365) for crypto (24/7 trading)
        return ((mean_r - risk_free) / std_r) * (365 ** 0.5)

    def _calc_max_drawdown(self, trades: list[dict]) -> float:
        """최대 낙폭 계산."""
        if not trades:
            return 0.0
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in trades:
            if t["side"] == "buy":
                equity -= t["amount_krw"] + t["commission"]
            else:
                equity += t["amount_krw"] - t["commission"]
            if equity > peak:
                peak = equity
            if peak > 0:
                dd = (peak - equity) / peak * 100
                if dd > max_dd:
                    max_dd = dd
        return max_dd
