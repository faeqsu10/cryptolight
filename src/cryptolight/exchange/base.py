from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class Balance:
    currency: str
    total: float
    available: float
    locked: float
    avg_buy_price: float = 0.0


@dataclass
class Candle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Ticker:
    symbol: str
    price: float
    change_rate: float
    volume_24h: float
    high_24h: float
    low_24h: float


@dataclass
class OrderResult:
    order_id: str
    symbol: str
    side: str  # bid(매수) / ask(매도)
    order_type: str
    price: float | None
    quantity: float | None
    amount: float | None  # 총 주문금액(KRW)
    state: str
    raw: dict[str, Any] | None = None


class ExchangeClient(ABC):
    @abstractmethod
    def get_balances(self) -> list[Balance]:
        ...

    @abstractmethod
    def get_balance(self, currency: str) -> Balance | None:
        ...

    @abstractmethod
    def get_candles(
        self, symbol: str, interval: str = "day", count: int = 200
    ) -> list[Candle]:
        ...

    @abstractmethod
    def get_ticker(self, symbol: str) -> Ticker:
        ...

    @abstractmethod
    def buy_market(self, symbol: str, amount_krw: float) -> OrderResult:
        ...

    @abstractmethod
    def sell_market(self, symbol: str, quantity: float) -> OrderResult:
        ...

    @abstractmethod
    def get_order(self, order_id: str) -> OrderResult:
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> OrderResult:
        ...
