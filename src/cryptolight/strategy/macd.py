"""MACD 전략 — 이동평균 수렴/발산"""

from cryptolight.exchange.base import Candle
from cryptolight.strategy.base import BaseStrategy, Signal


def calculate_ema(values: list[float], period: int) -> list[float]:
    """EMA(지수이동평균)를 계산한다."""
    if len(values) < period:
        return []

    multiplier = 2 / (period + 1)

    # 첫 EMA는 SMA로 시작
    ema = [sum(values[:period]) / period]

    for price in values[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])

    return ema


class MACDStrategy(BaseStrategy):
    def __init__(self, fast: int = 12, slow: int = 26, signal_period: int = 9):
        self.fast = fast
        self.slow = slow
        self.signal_period = signal_period

    def required_candle_count(self) -> int:
        return self.slow + self.signal_period + 1

    def analyze(self, candles: list[Candle]) -> Signal:
        if len(candles) < self.required_candle_count():
            return Signal(
                action="hold",
                symbol="",
                reason=f"캔들 부족 ({len(candles)}/{self.required_candle_count()})",
            )

        closes = [c.close for c in candles]

        ema_fast = calculate_ema(closes, self.fast)
        ema_slow = calculate_ema(closes, self.slow)

        # EMA(fast)와 EMA(slow)의 길이를 맞춘다
        # ema_fast는 len(closes) - fast + 1 개, ema_slow는 len(closes) - slow + 1 개
        # slow > fast이므로 ema_slow가 더 짧다. ema_fast의 뒷부분만 사용
        offset = len(ema_fast) - len(ema_slow)
        ema_fast_aligned = ema_fast[offset:]

        # MACD line = EMA(fast) - EMA(slow)
        macd_line = [f - s for f, s in zip(ema_fast_aligned, ema_slow)]

        # Signal line = EMA(signal_period) of MACD line
        signal_line = calculate_ema(macd_line, self.signal_period)

        if len(signal_line) < 2:
            return Signal(action="hold", symbol="", reason="MACD 계산 불가")

        # Histogram = MACD - Signal (길이 맞추기)
        macd_aligned = macd_line[len(macd_line) - len(signal_line) :]
        histogram = [m - s for m, s in zip(macd_aligned, signal_line)]

        macd = macd_aligned[-1]
        signal_val = signal_line[-1]
        hist = histogram[-1]

        prev_macd = macd_aligned[-2]
        prev_signal = signal_line[-2]

        indicators = {
            "macd": round(macd, 2),
            "signal": round(signal_val, 2),
            "histogram": round(hist, 2),
        }

        confidence = min(abs(hist) / closes[-1], 1.0) if closes[-1] != 0 else 0.0
        confidence = round(confidence, 4)

        # 골든크로스: 이전 MACD < Signal, 현재 MACD > Signal
        if prev_macd < prev_signal and macd > signal_val:
            return Signal(
                action="buy",
                symbol="",
                reason=f"MACD 골든크로스: MACD {macd:.2f} > Signal {signal_val:.2f}",
                confidence=confidence,
                indicators=indicators,
            )

        # 데드크로스: 이전 MACD > Signal, 현재 MACD < Signal
        if prev_macd > prev_signal and macd < signal_val:
            return Signal(
                action="sell",
                symbol="",
                reason=f"MACD 데드크로스: MACD {macd:.2f} < Signal {signal_val:.2f}",
                confidence=confidence,
                indicators=indicators,
            )

        return Signal(
            action="hold",
            symbol="",
            reason=f"MACD 중립: MACD {macd:.2f}, Signal {signal_val:.2f}",
            indicators=indicators,
        )
