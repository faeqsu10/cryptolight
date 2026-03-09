"""시장 국면 감지 — ADX + 볼린저밴드 폭 기반"""

import logging
import statistics

from cryptolight.exchange.base import Candle

logger = logging.getLogger("cryptolight.market.regime")


class MarketRegime:
    """시장 국면(trending/sideways/volatile)을 판단한다."""

    def __init__(
        self,
        adx_period: int = 14,
        bb_period: int = 20,
        adx_trend_threshold: float = 25.0,
        bb_volatile_threshold: float = 0.06,
    ):
        self.adx_period = adx_period
        self.bb_period = bb_period
        self.adx_trend_threshold = adx_trend_threshold
        self.bb_volatile_threshold = bb_volatile_threshold

    def detect(self, candles: list[Candle]) -> dict:
        """
        국면을 판단하고 결과를 반환한다.

        Returns:
            {
                "regime": "trending" | "sideways" | "volatile",
                "adx": float,
                "bb_bandwidth": float,
                "confidence": float,  # 0~1
                "trade_weight": float,  # 매매 가중치 (0~1)
            }
        """
        adx = self._calc_adx(candles)
        bb_bw = self._calc_bb_bandwidth(candles)

        if bb_bw >= self.bb_volatile_threshold:
            regime = "volatile"
            confidence = min(1.0, bb_bw / self.bb_volatile_threshold)
            trade_weight = 0.5  # 변동성 높으면 주의
        elif adx >= self.adx_trend_threshold:
            regime = "trending"
            confidence = min(1.0, adx / 50)
            trade_weight = 1.0  # 추세장에서 적극 매매
        else:
            regime = "sideways"
            confidence = 1.0 - (adx / self.adx_trend_threshold)
            trade_weight = 0.3  # 횡보장에서 매매 억제

        logger.info(
            "시장 국면: %s (ADX=%.1f, BB폭=%.4f, 매매가중치=%.1f)",
            regime, adx, bb_bw, trade_weight,
        )

        return {
            "regime": regime,
            "adx": round(adx, 2),
            "bb_bandwidth": round(bb_bw, 4),
            "confidence": round(confidence, 2),
            "trade_weight": round(trade_weight, 2),
        }

    def required_candle_count(self) -> int:
        return max(self.adx_period * 2 + 1, self.bb_period + 1)

    def _calc_adx(self, candles: list[Candle]) -> float:
        """ADX (Average Directional Index) 계산."""
        if len(candles) < self.adx_period * 2:
            return 0.0

        n = self.adx_period
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = [c.close for c in candles]

        # True Range, +DM, -DM
        tr_list, plus_dm_list, minus_dm_list = [], [], []
        for i in range(1, len(candles)):
            h, lo, pc = highs[i], lows[i], closes[i - 1]
            tr = max(h - lo, abs(h - pc), abs(lo - pc))
            tr_list.append(tr)

            up_move = highs[i] - highs[i - 1]
            down_move = lows[i - 1] - lows[i]
            plus_dm_list.append(up_move if up_move > down_move and up_move > 0 else 0)
            minus_dm_list.append(down_move if down_move > up_move and down_move > 0 else 0)

        if len(tr_list) < n:
            return 0.0

        # Wilder smoothing
        def wilder_smooth(values: list[float], period: int) -> list[float]:
            result = [sum(values[:period])]
            for v in values[period:]:
                result.append(result[-1] - result[-1] / period + v)
            return result

        atr = wilder_smooth(tr_list, n)
        plus_dm_s = wilder_smooth(plus_dm_list, n)
        minus_dm_s = wilder_smooth(minus_dm_list, n)

        # +DI, -DI, DX
        dx_list = []
        length = min(len(atr), len(plus_dm_s), len(minus_dm_s))
        for i in range(length):
            if atr[i] == 0:
                continue
            plus_di = 100 * plus_dm_s[i] / atr[i]
            minus_di = 100 * minus_dm_s[i] / atr[i]
            di_sum = plus_di + minus_di
            if di_sum == 0:
                continue
            dx_list.append(100 * abs(plus_di - minus_di) / di_sum)

        if len(dx_list) < n:
            return statistics.mean(dx_list) if dx_list else 0.0

        # ADX = DX의 Wilder smoothing
        adx_vals = wilder_smooth(dx_list, n)
        return adx_vals[-1] if adx_vals else 0.0

    def _calc_bb_bandwidth(self, candles: list[Candle]) -> float:
        """볼린저밴드 폭 (bandwidth) = (upper - lower) / middle."""
        if len(candles) < self.bb_period:
            return 0.0

        closes = [c.close for c in candles[-self.bb_period:]]
        sma = statistics.mean(closes)
        if sma == 0:
            return 0.0
        std = statistics.stdev(closes)
        upper = sma + 2 * std
        lower = sma - 2 * std
        return (upper - lower) / sma
