"""리스크 관리 모듈 — 주문 전 안전 검증"""

import logging
from dataclasses import dataclass

from cryptolight.storage.repository import TradeRepository

logger = logging.getLogger("cryptolight.risk")


@dataclass
class RiskCheckResult:
    allowed: bool
    reason: str


class RiskGuard:
    """주문 실행 전 리스크 검증을 수행한다."""

    COMMISSION_RATE = 0.0005  # 업비트 0.05%

    def __init__(
        self,
        max_order_amount_krw: float,
        daily_loss_limit_krw: float,
        max_positions: int = 5,
        stop_loss_pct: float = -5.0,
        take_profit_pct: float = 10.0,
        repo: TradeRepository | None = None,
    ):
        self.max_order_amount_krw = max_order_amount_krw
        self.daily_loss_limit_krw = daily_loss_limit_krw
        self.max_positions = max_positions
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self._repo = repo

    def check_buy(
        self,
        symbol: str,
        amount_krw: float,
        balance_krw: float,
        active_positions: int,
        already_holding: bool,
    ) -> RiskCheckResult:
        """매수 주문 전 리스크 체크"""
        # 1) 최대 주문 금액 제한
        if amount_krw > self.max_order_amount_krw:
            return RiskCheckResult(
                allowed=False,
                reason=f"주문 금액 {amount_krw:,.0f} > 한도 {self.max_order_amount_krw:,.0f} KRW",
            )

        # 2) 잔고 부족
        if amount_krw * (1 + self.COMMISSION_RATE) > balance_krw:
            return RiskCheckResult(
                allowed=False,
                reason=f"잔고 부족: 필요 {amount_krw:,.0f}, 가용 {balance_krw:,.0f} KRW",
            )

        # 3) 동시 보유 종목 수 제한
        if not already_holding and active_positions >= self.max_positions:
            return RiskCheckResult(
                allowed=False,
                reason=f"보유 종목 한도 초과: {active_positions}/{self.max_positions}",
            )

        # 4) 일일 손실 한도 체크
        if self._repo:
            daily_pnl = self._repo.get_daily_pnl()
            if daily_pnl["realized_pnl"] <= -self.daily_loss_limit_krw:
                return RiskCheckResult(
                    allowed=False,
                    reason=f"일일 손실 한도 도달: {daily_pnl['realized_pnl']:+,.0f} KRW (한도: -{self.daily_loss_limit_krw:,.0f})",
                )

        logger.info("리스크 체크 통과: %s 매수 %s KRW", symbol, f"{amount_krw:,.0f}")
        return RiskCheckResult(allowed=True, reason="통과")

    def check_stop_loss_take_profit(
        self, symbol: str, avg_price: float, quantity: float, current_price: float,
    ) -> str | None:
        """손절/익절 조건 확인. 해당되면 'stop_loss' 또는 'take_profit' 반환."""
        if quantity <= 0 or avg_price <= 0:
            return None

        pnl_pct = (current_price - avg_price) / avg_price * 100

        if pnl_pct <= self.stop_loss_pct:
            logger.warning(
                "손절 트리거: %s 손익률 %.2f%% <= %.2f%%",
                symbol, pnl_pct, self.stop_loss_pct,
            )
            return "stop_loss"

        if pnl_pct >= self.take_profit_pct:
            logger.info(
                "익절 트리거: %s 손익률 %.2f%% >= %.2f%%",
                symbol, pnl_pct, self.take_profit_pct,
            )
            return "take_profit"

        return None
