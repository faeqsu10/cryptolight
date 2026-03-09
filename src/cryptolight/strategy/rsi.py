import logging

from cryptolight.exchange.base import Candle
from cryptolight.strategy.base import BaseStrategy, Signal

logger = logging.getLogger("cryptolight.strategy.rsi")


def calculate_rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = deltas[-(period):]

    gains = [d for d in recent if d > 0]
    losses = [-d for d in recent if d < 0]

    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


class RSIStrategy(BaseStrategy):
    def __init__(
        self,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
    ):
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def required_candle_count(self) -> int:
        return self.period + 2

    def analyze(self, candles: list[Candle]) -> Signal:
        if len(candles) < self.required_candle_count():
            return Signal(
                action="hold",
                symbol="",
                reason=f"캔들 부족 ({len(candles)}/{self.required_candle_count()})",
            )

        closes = [c.close for c in candles]
        rsi = calculate_rsi(closes, self.period)

        if rsi is None:
            return Signal(action="hold", symbol="", reason="RSI 계산 불가")

        # 이전 RSI도 계산하여 방향성 확인
        prev_rsi = calculate_rsi(closes[:-1], self.period)

        indicators = {"rsi": round(rsi, 2), "prev_rsi": round(prev_rsi, 2) if prev_rsi else None}

        if rsi <= self.oversold:
            confidence = min((self.oversold - rsi) / self.oversold, 1.0)
            return Signal(
                action="buy",
                symbol="",
                reason=f"RSI {rsi:.1f} 과매도 구간 진입",
                confidence=round(confidence, 2),
                indicators=indicators,
            )

        if rsi >= self.overbought:
            confidence = min((rsi - self.overbought) / (100 - self.overbought), 1.0)
            return Signal(
                action="sell",
                symbol="",
                reason=f"RSI {rsi:.1f} 과매수 구간 진입",
                confidence=round(confidence, 2),
                indicators=indicators,
            )

        return Signal(
            action="hold",
            symbol="",
            reason=f"RSI {rsi:.1f} 중립 구간",
            indicators=indicators,
        )
