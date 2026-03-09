import logging
from dataclasses import dataclass

from cryptolight.exchange.base import OrderResult
from cryptolight.execution.base import BaseBroker
from cryptolight.storage.models import TradeRecord
from cryptolight.storage.repository import TradeRepository

logger = logging.getLogger("cryptolight.execution.paper")


@dataclass
class PaperPosition:
    symbol: str
    quantity: float = 0.0
    avg_price: float = 0.0
    total_cost: float = 0.0


class PaperBroker(BaseBroker):
    """가상 매매 실행기. 실제 주문 없이 시뮬레이션한다."""

    COMMISSION_RATE = 0.0005  # 업비트 0.05%

    def __init__(self, initial_balance: float, repo: TradeRepository | None = None):
        self.balance_krw = initial_balance
        self.initial_balance = initial_balance
        self.positions: dict[str, PaperPosition] = {}
        self._repo = repo

        # DB에서 포지션 복구
        if self._repo:
            saved_positions, saved_balance = self._repo.load_positions()
            for symbol, data in saved_positions.items():
                self.positions[symbol] = PaperPosition(
                    symbol=data["symbol"],
                    quantity=data["quantity"],
                    avg_price=data["avg_price"],
                    total_cost=data["total_cost"],
                )
            if saved_balance is not None:
                self.balance_krw = saved_balance

    def buy_market(self, symbol: str, amount_krw: float, current_price: float, reason: str = "") -> OrderResult | None:
        commission = amount_krw * self.COMMISSION_RATE
        total_cost = amount_krw + commission

        if total_cost > self.balance_krw:
            logger.warning("잔고 부족: 필요 %s, 가용 %s", f"{total_cost:,.0f}", f"{self.balance_krw:,.0f}")
            return None

        quantity = amount_krw / current_price
        self.balance_krw -= total_cost

        # 포지션 업데이트
        pos = self.positions.get(symbol, PaperPosition(symbol=symbol))
        new_total = pos.quantity * pos.avg_price + amount_krw
        pos.quantity += quantity
        pos.avg_price = new_total / pos.quantity if pos.quantity > 0 else 0
        pos.total_cost += amount_krw
        self.positions[symbol] = pos

        logger.info(
            "[PAPER 매수] %s %.8f @ %s (수수료: %s)",
            symbol, quantity, f"{current_price:,.0f}", f"{commission:,.0f}",
        )

        # 거래 기록 저장
        trade = TradeRecord(
            symbol=symbol, side="buy", price=current_price,
            quantity=quantity, amount_krw=amount_krw,
            commission=commission, reason=reason,
        )
        if self._repo:
            self._repo.save_trade(trade)
            self._repo.save_positions(self.positions, self.balance_krw)

        return OrderResult(
            order_id=f"paper-buy-{symbol}",
            symbol=symbol, side="bid", order_type="price",
            price=current_price, quantity=quantity, amount=amount_krw,
            state="done",
        )

    def sell_market(self, symbol: str, quantity: float, current_price: float, reason: str = "") -> OrderResult | None:
        pos = self.positions.get(symbol)
        if not pos or pos.quantity < quantity:
            available = pos.quantity if pos else 0
            logger.warning("보유 수량 부족: 필요 %.8f, 보유 %.8f", quantity, available)
            return None

        proceeds = quantity * current_price
        commission = proceeds * self.COMMISSION_RATE
        self.balance_krw += proceeds - commission

        # 포지션 업데이트
        pos.quantity -= quantity
        if pos.quantity < 1e-10:
            pos.quantity = 0
            pos.avg_price = 0

        logger.info(
            "[PAPER 매도] %s %.8f @ %s (수수료: %s)",
            symbol, quantity, f"{current_price:,.0f}", f"{commission:,.0f}",
        )

        trade = TradeRecord(
            symbol=symbol, side="sell", price=current_price,
            quantity=quantity, amount_krw=proceeds,
            commission=commission, reason=reason,
        )
        if self._repo:
            self._repo.save_trade(trade)
            self._repo.save_positions(self.positions, self.balance_krw)

        return OrderResult(
            order_id=f"paper-sell-{symbol}",
            symbol=symbol, side="ask", order_type="market",
            price=current_price, quantity=quantity, amount=proceeds,
            state="done",
        )

    def get_equity(self, prices: dict[str, float]) -> float:
        """총 자산 = 현금 + 보유 코인 평가액"""
        equity = self.balance_krw
        for symbol, pos in self.positions.items():
            if pos.quantity > 0 and symbol in prices:
                equity += pos.quantity * prices[symbol]
        return equity

    def get_total_pnl(self, prices: dict[str, float]) -> dict:
        equity = self.get_equity(prices)
        pnl = equity - self.initial_balance
        pnl_pct = (pnl / self.initial_balance) * 100

        return {
            "initial_balance": self.initial_balance,
            "current_equity": equity,
            "total_pnl": pnl,
            "total_pnl_pct": pnl_pct,
            "cash": self.balance_krw,
            "positions": {
                s: {"qty": p.quantity, "avg_price": p.avg_price}
                for s, p in self.positions.items() if p.quantity > 0
            },
        }

    def summary_text(self, prices: dict[str, float]) -> str:
        info = self.get_total_pnl(prices)
        lines = [
            f"현금: {info['cash']:,.0f} KRW",
            f"총 자산: {info['current_equity']:,.0f} KRW",
            f"손익: {info['total_pnl']:+,.0f} KRW ({info['total_pnl_pct']:+.2f}%)",
        ]
        for symbol, pos in info["positions"].items():
            cur_price = prices.get(symbol, 0)
            pnl = (cur_price - pos["avg_price"]) * pos["qty"]
            lines.append(f"  {symbol}: {pos['qty']:.8f} (평단: {pos['avg_price']:,.0f}, 평가손익: {pnl:+,.0f})")
        return "\n".join(lines)
