"""실거래 브로커 — 업비트 실주문 실행 (리스크 가드 필수)"""

import logging

from cryptolight.exchange.base import OrderResult
from cryptolight.exchange.upbit import UpbitClient
from cryptolight.execution.base import BaseBroker
from cryptolight.storage.models import TradeRecord
from cryptolight.storage.repository import TradeRepository

logger = logging.getLogger("cryptolight.execution.live")


class LiveBroker(BaseBroker):
    """업비트 실거래 주문 실행기."""

    COMMISSION_RATE = 0.0005  # 업비트 0.05%

    def __init__(self, client: UpbitClient, repo: TradeRepository | None = None):
        self._client = client
        self._repo = repo

    def buy_market(self, symbol: str, amount_krw: float, current_price: float, reason: str = "") -> OrderResult | None:
        try:
            order = self._client.buy_market(symbol, amount_krw)
            logger.info("[LIVE 매수] %s %s KRW — 주문ID: %s", symbol, f"{amount_krw:,.0f}", order.order_id)

            quantity = amount_krw / current_price  # 추정치 (체결 후 조회 필요)
            commission = amount_krw * self.COMMISSION_RATE

            if self._repo:
                trade = TradeRecord(
                    symbol=symbol, side="buy", price=current_price,
                    quantity=quantity, amount_krw=amount_krw,
                    commission=commission, reason=reason,
                )
                self._repo.save_trade(trade)

            return order
        except Exception:
            logger.exception("매수 주문 실패: %s", symbol)
            return None

    def sell_market(self, symbol: str, quantity: float, current_price: float, reason: str = "") -> OrderResult | None:
        try:
            order = self._client.sell_market(symbol, quantity)
            logger.info("[LIVE 매도] %s %.8f — 주문ID: %s", symbol, quantity, order.order_id)

            proceeds = quantity * current_price
            commission = proceeds * self.COMMISSION_RATE

            if self._repo:
                trade = TradeRecord(
                    symbol=symbol, side="sell", price=current_price,
                    quantity=quantity, amount_krw=proceeds,
                    commission=commission, reason=reason,
                )
                self._repo.save_trade(trade)

            return order
        except Exception:
            logger.exception("매도 주문 실패: %s", symbol)
            return None
