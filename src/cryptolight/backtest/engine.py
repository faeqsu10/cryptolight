import math
import statistics
from dataclasses import dataclass, field

from cryptolight.exchange.base import Candle
from cryptolight.market.regime import MarketRegime
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
    daily_returns: list[float] = field(default_factory=list)
    # Buy & Hold 벤치마크
    buy_hold_return_pct: float = 0.0
    buy_hold_final_equity: float = 0.0
    alpha_pct: float = 0.0  # 전략 수익률 - Buy&Hold 수익률


class BacktestEngine:
    """캔들 데이터를 순회하며 전략 시그널에 따라 매매를 시뮬레이션한다."""

    def __init__(
        self,
        strategy: BaseStrategy,
        initial_balance: float = 1_000_000,
        order_amount: float = 50_000,
        commission_rate: float = 0.0005,
        slippage_pct: float = 0.0,
        spread_pct: float = 0.0,
        enable_regime: bool = False,
        candle_interval: str = "day",
    ):
        self.strategy = strategy
        self.initial_balance = initial_balance
        self.order_amount = order_amount
        self.commission_rate = commission_rate
        self.slippage_pct = slippage_pct / 100  # % → 비율
        self.spread_pct = spread_pct / 100
        self.candle_interval = candle_interval
        self._regime_detector = MarketRegime() if enable_regime else None

    def _apply_slippage(self, price: float, side: str) -> float:
        """매수 시 불리한 방향으로 슬리피지+스프레드 적용."""
        impact = self.slippage_pct + self.spread_pct / 2
        if side == "buy":
            return price * (1 + impact)
        return price * (1 - impact)

    def _candles_per_year(self) -> int:
        """캔들 주기에 따른 연간 캔들 수 반환."""
        interval_map = {
            "day": 365,
            "minute240": 365 * 6,      # 4시간봉: 하루 6개
            "minute60": 365 * 24,      # 1시간봉: 하루 24개
            "minute30": 365 * 48,      # 30분봉
            "minute15": 365 * 96,      # 15분봉
            "minute10": 365 * 144,     # 10분봉
            "minute5": 365 * 288,      # 5분봉
            "minute3": 365 * 480,      # 3분봉
            "minute1": 365 * 1440,     # 1분봉
        }
        return interval_map.get(self.candle_interval, 365)

    def _calc_buy_hold(self, candles: list[Candle], start_idx: int) -> tuple[float, float]:
        """Buy & Hold 벤치마크 계산."""
        if start_idx >= len(candles):
            return 0.0, self.initial_balance
        entry_price = candles[start_idx].close
        exit_price = candles[-1].close
        qty = (self.initial_balance - self.initial_balance * self.commission_rate) / entry_price
        final_val = qty * exit_price - exit_price * qty * self.commission_rate
        bh_return = ((final_val - self.initial_balance) / self.initial_balance) * 100
        return round(bh_return, 2), round(final_val, 2)

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

            # 백테스트에서도 시장 국면 감지 (실전과 동일)
            if self._regime_detector and hasattr(self.strategy, 'regime'):
                if len(window) >= self._regime_detector.required_candle_count():
                    regime_info = self._regime_detector.detect(window)
                    self.strategy.regime = regime_info["regime"]

            signal = self.strategy.analyze(window)
            price = candles[i].close

            if signal.action == "buy" and balance >= self.order_amount:
                exec_price = self._apply_slippage(price, "buy")
                amount = min(self.order_amount, balance)
                commission = amount * self.commission_rate
                cost = amount + commission

                if cost <= balance:
                    qty = amount / exec_price
                    total_value = position_qty * position_avg_price + amount
                    position_qty += qty
                    position_avg_price = total_value / position_qty if position_qty > 0 else 0
                    balance -= cost
                    buy_trades += 1

            elif signal.action == "sell" and position_qty > 0:
                exec_price = self._apply_slippage(price, "sell")
                proceeds = position_qty * exec_price
                commission = proceeds * self.commission_rate
                net_proceeds = proceeds - commission

                if exec_price > position_avg_price:
                    winning_trades += 1
                else:
                    losing_trades += 1

                balance += net_proceeds
                position_qty = 0.0
                position_avg_price = 0.0
                sell_trades += 1

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

        # Sharpe ratio (캔들 주기에 맞춰 연율화)
        candles_per_year = self._candles_per_year()
        if len(daily_returns) >= 2:
            std = statistics.stdev(daily_returns)
            if std > 0:
                sharpe_ratio = (statistics.mean(daily_returns) / std) * math.sqrt(candles_per_year)
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
        max_drawdown_pct *= 100

        # 승률
        total_completed = winning_trades + losing_trades
        win_rate = (winning_trades / total_completed * 100) if total_completed > 0 else 0.0
        total_trades = buy_trades + sell_trades

        # Buy & Hold 벤치마크
        bh_return, bh_equity = self._calc_buy_hold(candles, required)
        alpha = round(total_return_pct - bh_return, 2)

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
            buy_hold_return_pct=bh_return,
            buy_hold_final_equity=bh_equity,
            alpha_pct=alpha,
        )

    def summary_text(self, result: BacktestResult) -> str:
        """결과를 사람이 읽기 좋은 텍스트로 반환한다."""
        lines = [
            "=== 백테스트 결과 ===",
            f"초기 자산: {result.initial_balance:,.0f} KRW",
            f"최종 자산: {result.final_equity:,.0f} KRW",
            f"총 수익률: {result.total_return_pct:+.2f}%",
            f"Buy&Hold: {result.buy_hold_return_pct:+.2f}% ({result.buy_hold_final_equity:,.0f} KRW)",
            f"Alpha: {result.alpha_pct:+.2f}%",
            f"샤프 비율: {result.sharpe_ratio:.4f}",
            f"최대 낙폭: {result.max_drawdown_pct:.2f}%",
            f"승률: {result.win_rate:.1f}%",
            f"총 거래: {result.total_trades}회 (매수 {result.buy_trades} / 매도 {result.sell_trades})",
        ]
        return "\n".join(lines)
