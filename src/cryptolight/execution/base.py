from abc import ABC, abstractmethod

from cryptolight.exchange.base import OrderResult


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
