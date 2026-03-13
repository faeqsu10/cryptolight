"""변동성 돌파 전략 — Larry Williams"""

from cryptolight.exchange.base import Candle
from cryptolight.strategy.base import BaseStrategy, Signal


class VolatilityBreakoutStrategy(BaseStrategy):
    def __init__(self, k: float = 0.5):
        self.k = k

    def get_tunable_params(self) -> dict:
        return {"k": self.k}

    def required_candle_count(self) -> int:
        return 2

    def analyze(self, candles: list[Candle]) -> Signal:
        if len(candles) < self.required_candle_count():
            return Signal(
                action="hold",
                symbol="",
                reason=f"캔들 부족 ({len(candles)}/{self.required_candle_count()})",
            )

        prev = candles[-2]
        curr = candles[-1]

        range_ = prev.high - prev.low
        target_price = curr.open + range_ * self.k
        current_price = curr.close

        indicators = {"target_price": target_price, "range": range_, "k": self.k}

        if current_price >= target_price and range_ > 0:
            confidence = min((current_price - target_price) / range_, 1.0)
            return Signal(
                action="buy",
                symbol="",
                reason=f"변동성 돌파: 현재가 {current_price:,.0f} >= 목표가 {target_price:,.0f}",
                confidence=round(confidence, 2),
                indicators=indicators,
            )

        if current_price < curr.open:
            return Signal(
                action="sell",
                symbol="",
                reason=f"하락 반전: 현재가 {current_price:,.0f} < 시가 {curr.open:,.0f}",
                indicators=indicators,
            )

        return Signal(
            action="hold",
            symbol="",
            reason=f"대기: 현재가 {current_price:,.0f}, 목표가 {target_price:,.0f}",
            indicators=indicators,
        )
