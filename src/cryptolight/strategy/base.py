from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from cryptolight.exchange.base import Candle


@dataclass
class Signal:
    action: str  # buy / sell / hold
    symbol: str
    reason: str
    confidence: float = 0.0  # 0.0 ~ 1.0
    indicators: dict = field(default_factory=dict)


class BaseStrategy(ABC):
    @abstractmethod
    def analyze(self, candles: list[Candle]) -> Signal:
        """캔들 데이터를 받아 시그널을 반환한다."""
        ...

    @abstractmethod
    def required_candle_count(self) -> int:
        """전략에 필요한 최소 캔들 수."""
        ...
