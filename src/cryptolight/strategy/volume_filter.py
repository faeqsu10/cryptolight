"""거래량 필터 — 평균 거래량 대비 현재 거래량으로 시그널 품질 판단"""

import logging
import statistics

from cryptolight.exchange.base import Candle
from cryptolight.strategy.base import Signal

logger = logging.getLogger("cryptolight.strategy.volume_filter")


class VolumeFilter:
    """거래량 기반으로 시그널을 필터링/강화한다."""

    def __init__(
        self,
        period: int = 20,
        min_ratio: float = 0.5,
        boost_ratio: float = 2.0,
        boost_factor: float = 1.2,
    ):
        """
        Args:
            period: 평균 거래량 산출 기간
            min_ratio: 이 비율 미만이면 시그널 무시
            boost_ratio: 이 비율 이상이면 confidence 부스트
            boost_factor: 부스트 시 confidence 배수
        """
        self.period = period
        self.min_ratio = min_ratio
        self.boost_ratio = boost_ratio
        self.boost_factor = boost_factor

    def apply(self, signal: Signal, candles: list[Candle]) -> Signal:
        """시그널에 거래량 필터를 적용한다."""
        if signal.action == "hold" or len(candles) < self.period + 1:
            return signal

        volumes = [c.volume for c in candles[-(self.period + 1):-1]]
        current_volume = candles[-1].volume
        avg_volume = statistics.mean(volumes) if volumes else 0

        if avg_volume <= 0:
            return signal

        volume_ratio = current_volume / avg_volume

        signal.indicators["volume_ratio"] = round(volume_ratio, 2)

        # 거래량 부족 → hold로 전환
        if volume_ratio < self.min_ratio:
            logger.info(
                "거래량 부족 필터: %s → hold (ratio=%.2f < %.2f)",
                signal.action, volume_ratio, self.min_ratio,
            )
            return Signal(
                action="hold",
                symbol=signal.symbol,
                reason=f"거래량 부족 (ratio={volume_ratio:.2f})",
                confidence=0.0,
                indicators=signal.indicators,
            )

        # 거래량 폭증 → confidence 부스트
        if volume_ratio >= self.boost_ratio:
            boosted = min(1.0, signal.confidence * self.boost_factor)
            logger.info(
                "거래량 부스트: confidence %.2f → %.2f (ratio=%.2f)",
                signal.confidence, boosted, volume_ratio,
            )
            signal.confidence = boosted

        return signal
