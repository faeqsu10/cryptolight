import math
import statistics
from dataclasses import dataclass, field

from cryptolight.exchange.base import Candle
from cryptolight.strategy.base import BaseStrategy


@dataclass
class BacktestResult:
    total_return_pct: float       # 총 수익률 %
    sharpe_ratio: float           # 샤프 비율 (연율화)
    max_drawdown_pct: float       # 최대 낙폭 %
    win_rate: float               # 승률 %
    total_trades: int             # 총 거래 수
    buy_trades: int
    sell_trades: int
    initial_balance: float
    final_equity: float
    daily_returns: list[float] = field(default_factory=list)  # 일별 수익률


class BacktestEngine:
    """캔들 데이터를 순회하며 전략 시그널에 따라 매매를 시뮬레이션한다."""

    def __init__(
        self,
        strategy: BaseStrategy,
        initial_balance: float = 1_000_000,
        order_amount: float = 50_000,
        commission_rate: float = 0.0005,
    ):
        self.strategy = strategy
        self.initial_balance = initial_balance
        self.order_amount = order_amount
        self.commission_rate = commission_rate

    def run(self, candles: list[Candle]) -> BacktestResult:
        """캔들 데이터를 순회하며 백테스트를 실행한다."""
        balance = self.initial_balance
        position_qty = 0.0
        position_avg_price = 0.0

        buy_trades = 0
        sell_trades = 0
        winning_trades = 0
        losing_trades = 0

        equity_curve: list[float] = [self.initial_balance]
        required = self.strategy.required_candle_count()

        for i in range(required, len(candles)):
            window = candles[: i + 1]
            signal = self.strategy.analyze(window)
            price = candles[i].close

            if signal.action == "buy" and balance >= self.order_amount:
                # 매수: order_amount만큼
                amount = min(self.order_amount, balance)
                commission = amount * self.commission_rate
                cost = amount + commission

                if cost <= balance:
                    qty = amount / price
                    # 평단가 갱신
                    total_value = position_qty * position_avg_price + amount
                    position_qty += qty
                    position_avg_price = total_value / position_qty if position_qty > 0 else 0
                    balance -= cost
                    buy_trades += 1

            elif signal.action == "sell" and position_qty > 0:
                # 매도: 전량
                proceeds = position_qty * price
                commission = proceeds * self.commission_rate
                net_proceeds = proceeds - commission

                # 승패 판정
                if price > position_avg_price:
                    winning_trades += 1
                else:
                    losing_trades += 1

                balance += net_proceeds
                position_qty = 0.0
                position_avg_price = 0.0
                sell_trades += 1

            # 현재 자산 기록 (현금 + 코인 평가액)
            equity = balance + position_qty * price
            equity_curve.append(equity)

        # ── 결과 지표 계산 ──
        final_equity = equity_curve[-1]
        total_return_pct = ((final_equity - self.initial_balance) / self.initial_balance) * 100

        # 일별 수익률
        daily_returns: list[float] = []
        for i in range(1, len(equity_curve)):
            if equity_curve[i - 1] != 0:
                ret = (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
                daily_returns.append(ret)

        # Sharpe ratio (연율화, 코인은 365일)
        if len(daily_returns) >= 2:
            std = statistics.stdev(daily_returns)
            if std > 0:
                sharpe_ratio = (statistics.mean(daily_returns) / std) * math.sqrt(365)
            else:
                sharpe_ratio = 0.0
        else:
            sharpe_ratio = 0.0

        # MDD (최대 낙폭)
        max_drawdown_pct = 0.0
        peak = equity_curve[0]
        for eq in equity_curve[1:]:
            if eq > peak:
                peak = eq
            drawdown = (eq - peak) / peak
            if drawdown < max_drawdown_pct:
                max_drawdown_pct = drawdown
        max_drawdown_pct *= 100  # %로 변환

        # 승률
        total_completed = winning_trades + losing_trades
        win_rate = (winning_trades / total_completed * 100) if total_completed > 0 else 0.0

        total_trades = buy_trades + sell_trades

        return BacktestResult(
            total_return_pct=round(total_return_pct, 2),
            sharpe_ratio=round(sharpe_ratio, 4),
            max_drawdown_pct=round(max_drawdown_pct, 2),
            win_rate=round(win_rate, 2),
            total_trades=total_trades,
            buy_trades=buy_trades,
            sell_trades=sell_trades,
            initial_balance=self.initial_balance,
            final_equity=round(final_equity, 2),
            daily_returns=daily_returns,
        )

    def summary_text(self, result: BacktestResult) -> str:
        """결과를 사람이 읽기 좋은 텍스트로 반환한다."""
        lines = [
            "=== 백테스트 결과 ===",
            f"초기 자산: {result.initial_balance:,.0f} KRW",
            f"최종 자산: {result.final_equity:,.0f} KRW",
            f"총 수익률: {result.total_return_pct:+.2f}%",
            f"샤프 비율: {result.sharpe_ratio:.4f}",
            f"최대 낙폭: {result.max_drawdown_pct:.2f}%",
            f"승률: {result.win_rate:.1f}%",
            f"총 거래: {result.total_trades}회 (매수 {result.buy_trades} / 매도 {result.sell_trades})",
        ]
        return "\n".join(lines)
