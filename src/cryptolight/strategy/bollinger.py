"""볼린저밴드 전략 — Mean Reversion"""

import statistics

from cryptolight.exchange.base import Candle
from cryptolight.strategy.base import BaseStrategy, Signal


class BollingerStrategy(BaseStrategy):
    def __init__(self, period: int = 20, std_mult: float = 2.5):
        self.period = period
        self.std_mult = std_mult

    def required_candle_count(self) -> int:
        return self.period

    def analyze(self, candles: list[Candle]) -> Signal:
        if len(candles) < self.required_candle_count():
            return Signal(
                action="hold",
                symbol="",
                reason=f"캔들 부족 ({len(candles)}/{self.required_candle_count()})",
            )

        closes = [c.close for c in candles[-self.period :]]
        close = closes[-1]

        middle = statistics.mean(closes)
        std = statistics.pstdev(closes)

        upper = middle + self.std_mult * std
        lower = middle - self.std_mult * std

        pct_b = (close - lower) / (upper - lower) if upper != lower else 0.5

        indicators = {
            "upper": round(upper, 0),
            "lower": round(lower, 0),
            "middle": round(middle, 0),
            "pct_b": round(pct_b, 4),
        }

        if close <= lower:
            confidence = min(abs(lower - close) / lower, 1.0) if lower != 0 else 0.0
            return Signal(
                action="buy",
                symbol="",
                reason=f"볼린저 하단 터치: 종가 {close:,.0f} <= 하단 {lower:,.0f}",
                confidence=round(confidence, 4),
                indicators=indicators,
            )

        if close >= upper:
            confidence = min(abs(close - upper) / upper, 1.0) if upper != 0 else 0.0
            return Signal(
                action="sell",
                symbol="",
                reason=f"볼린저 상단 터치: 종가 {close:,.0f} >= 상단 {upper:,.0f}",
                confidence=round(confidence, 4),
                indicators=indicators,
            )

        return Signal(
            action="hold",
            symbol="",
            reason=f"볼린저 중립: 종가 {close:,.0f}, %B {pct_b:.4f}",
            indicators=indicators,
        )
