"""실거래 브로커 — 업비트 실주문 실행 (리스크 가드 필수)"""

import logging
import threading
import time

from cryptolight.exchange.base import OrderResult
from cryptolight.exchange.upbit import UpbitClient
from cryptolight.execution.base import BaseBroker, PositionInfo
from cryptolight.storage.models import TradeRecord
from cryptolight.storage.repository import TradeRepository

logger = logging.getLogger("cryptolight.execution.live")


class LiveBroker(BaseBroker):
    """업비트 실거래 주문 실행기."""

    def __init__(
        self,
        client: UpbitClient,
        repo: TradeRepository | None = None,
        absolute_max_order_krw: float = 500_000,
        commission_rate: float = 0.0005,
    ):
        self._client = client
        self._repo = repo
        self.absolute_max_order_krw = absolute_max_order_krw
        self.commission_rate = commission_rate
        self._order_lock = threading.Lock()

    def _verify_order(self, order: OrderResult, max_retries: int = 3) -> OrderResult:
        """주문 체결 상태를 확인한다. done/cancel 될 때까지 재조회."""
        for i in range(max_retries):
            try:
                verified = self._client.get_order(order.order_id)
                if verified.state in ("done", "cancel"):
                    return verified
                time.sleep(1 * (i + 1))
            except Exception:
                logger.warning("주문 확인 실패 (%d/%d): %s", i + 1, max_retries, order.order_id)
                time.sleep(1)
        logger.warning("주문 상태 미확정: %s (state=%s)", order.order_id, order.state)
        return order

    def buy_market(self, symbol: str, amount_krw: float, current_price: float, reason: str = "", strategy: str = "") -> OrderResult | None:
        # 하드캡 검증
        if amount_krw > self.absolute_max_order_krw:
            logger.error(
                "하드캡 초과 차단: %s KRW > %s KRW",
                f"{amount_krw:,.0f}", f"{self.absolute_max_order_krw:,.0f}",
            )
            return None

        with self._order_lock:
            try:
                order = self._client.buy_market(symbol, amount_krw)
                logger.info("[LIVE 매수] %s %s KRW — 주문ID: %s", symbol, f"{amount_krw:,.0f}", order.order_id)

                # 주문 체결 확인
                verified = self._verify_order(order)
                if verified.state == "cancel":
                    logger.warning("매수 주문 취소됨: %s", order.order_id)
                    return None

                # 체결 정보 사용 (가능 시), 아니면 추정치
                actual_price = verified.price or current_price
                actual_qty = verified.quantity or (amount_krw / current_price)
                commission = amount_krw * self.commission_rate

                if self._repo:
                    trade = TradeRecord(
                        symbol=symbol, side="buy", price=actual_price,
                        quantity=actual_qty, amount_krw=amount_krw,
                        commission=commission, reason=reason, strategy=strategy,
                    )
                    self._repo.save_trade(trade)

                return verified
            except Exception:
                logger.exception("매수 주문 실패: %s", symbol)
                return None

    def sell_market(self, symbol: str, quantity: float, current_price: float, reason: str = "", strategy: str = "") -> OrderResult | None:
        with self._order_lock:
            try:
                order = self._client.sell_market(symbol, quantity)
                logger.info("[LIVE 매도] %s %.8f — 주문ID: %s", symbol, quantity, order.order_id)

                # 주문 체결 확인
                verified = self._verify_order(order)
                if verified.state == "cancel":
                    logger.warning("매도 주문 취소됨: %s", order.order_id)
                    return None

                actual_price = verified.price or current_price
                proceeds = quantity * actual_price
                commission = proceeds * self.commission_rate

                if self._repo:
                    trade = TradeRecord(
                        symbol=symbol, side="sell", price=actual_price,
                        quantity=quantity, amount_krw=proceeds,
                        commission=commission, reason=reason, strategy=strategy,
                    )
                    self._repo.save_trade(trade)

                return verified
            except Exception:
                logger.exception("매도 주문 실패: %s", symbol)
                return None

    def get_balance_krw(self) -> float:
        """업비트에서 현금 잔고를 조회한다."""
        try:
            balances = self._client.get_balances()
            for b in balances:
                if b.currency == "KRW":
                    return b.balance
        except Exception:
            logger.exception("잔고 조회 실패")
        return 0.0

    def get_positions(self) -> dict[str, PositionInfo]:
        """업비트에서 보유 포지션을 조회한다."""
        try:
            balances = self._client.get_balances()
            positions: dict[str, PositionInfo] = {}
            for b in balances:
                if b.currency != "KRW" and b.balance > 0:
                    symbol = f"KRW-{b.currency}"
                    positions[symbol] = PositionInfo(
                        symbol=symbol,
                        quantity=b.balance,
                        avg_price=b.avg_buy_price,
                        total_cost=b.balance * b.avg_buy_price,
                    )
            return positions
        except Exception:
            logger.exception("포지션 조회 실패")
            return {}

    def get_equity(self, prices: dict[str, float]) -> float:
        """총 자산 = 현금 + 보유 코인 평가액"""
        equity = self.get_balance_krw()
        for symbol, pos in self.get_positions().items():
            equity += pos.quantity * prices.get(symbol, 0)
        return equity

    def get_total_pnl(self, prices: dict[str, float]) -> dict:
        """총 손익 정보를 반환한다."""
        cash = self.get_balance_krw()
        equity = cash
        pos_info = {}
        for symbol, pos in self.get_positions().items():
            equity += pos.quantity * prices.get(symbol, 0)
            pos_info[symbol] = {"qty": pos.quantity, "avg_price": pos.avg_price}
        return {
            "initial_balance": 0,
            "current_equity": equity,
            "total_pnl": 0,
            "total_pnl_pct": 0,
            "cash": cash,
            "positions": pos_info,
        }

    def summary_text(self, prices: dict[str, float]) -> str:
        """현재 상태 요약 텍스트를 반환한다."""
        cash = self.get_balance_krw()
        equity = cash
        lines = [f"현금: {cash:,.0f} KRW"]
        for symbol, pos in self.get_positions().items():
            price = prices.get(symbol, 0)
            equity += pos.quantity * price
            pnl = (price - pos.avg_price) * pos.quantity
            lines.append(f"  {symbol}: {pos.quantity:.8f} (평단: {pos.avg_price:,.0f}, 평가손익: {pnl:+,.0f})")
        lines.insert(1, f"총 자산: {equity:,.0f} KRW")
        return "\n".join(lines)
