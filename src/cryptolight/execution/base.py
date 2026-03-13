from abc import ABC, abstractmethod
from dataclasses import dataclass

from cryptolight.exchange.base import OrderResult


@dataclass
class PositionInfo:
    """브로커 공통 포지션 정보."""
    symbol: str
    quantity: float = 0.0
    avg_price: float = 0.0
    total_cost: float = 0.0


class BaseBroker(ABC):
    @abstractmethod
    def buy_market(
        self, symbol: str, amount_krw: float, current_price: float,
        reason: str = "", strategy: str = "",
    ) -> OrderResult | None:
        ...

    @abstractmethod
    def sell_market(
        self, symbol: str, quantity: float, current_price: float,
        reason: str = "", strategy: str = "",
    ) -> OrderResult | None:
        ...

    @abstractmethod
    def get_balance_krw(self) -> float:
        """현금 잔고를 반환한다."""
        ...

    @abstractmethod
    def get_positions(self) -> dict[str, PositionInfo]:
        """보유 포지션을 반환한다. {symbol: PositionInfo}"""
        ...

    @abstractmethod
    def get_equity(self, prices: dict[str, float]) -> float:
        """총 자산 = 현금 + 보유 코인 평가액"""
        ...

    @abstractmethod
    def get_total_pnl(self, prices: dict[str, float]) -> dict:
        """총 손익 정보를 반환한다."""
        ...

    @abstractmethod
    def summary_text(self, prices: dict[str, float]) -> str:
        """현재 상태 요약 텍스트를 반환한다."""
        ...

    def is_holding(self, symbol: str) -> bool:
        """특정 종목을 보유하고 있는지 확인한다."""
        pos = self.get_positions().get(symbol)
        return pos is not None and pos.quantity > 0

    def get_position(self, symbol: str) -> PositionInfo | None:
        """특정 종목의 포지션을 반환한다. 없으면 None."""
        pos = self.get_positions().get(symbol)
        if pos and pos.quantity > 0:
            return pos
        return None
