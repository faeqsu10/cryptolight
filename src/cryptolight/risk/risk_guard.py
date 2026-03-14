"""리스크 관리 모듈 — 주문 전 안전 검증, 손절/익절/트레일링 스톱"""

import logging
import threading
from dataclasses import dataclass

from cryptolight.storage.repository import TradeRepository

logger = logging.getLogger("cryptolight.risk")


@dataclass
class RiskCheckResult:
    allowed: bool
    reason: str


class RiskGuard:
    """주문 실행 전 리스크 검증을 수행한다."""

    def __init__(
        self,
        max_order_amount_krw: float,
        daily_loss_limit_krw: float,
        max_positions: int = 5,
        stop_loss_pct: float = -5.0,
        take_profit_pct: float = 10.0,
        trailing_stop_pct: float = 0.0,
        repo: TradeRepository | None = None,
        commission_rate: float = 0.0005,
    ):
        self.max_order_amount_krw = max_order_amount_krw
        self.daily_loss_limit_krw = daily_loss_limit_krw
        self.max_positions = max_positions
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.trailing_stop_pct = trailing_stop_pct
        self._repo = repo
        self.commission_rate = commission_rate
        # 트레일링 스톱: 종목별 최고가 추적
        self._trailing_highs: dict[str, float] = {}
        self._trailing_lock = threading.Lock()

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
        if amount_krw * (1 + self.commission_rate) > balance_krw:
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
        """손절/익절/트레일링 스톱 조건 확인. 스레드 안전."""
        if quantity <= 0 or avg_price <= 0:
            return None

        pnl_pct = (current_price - avg_price) / avg_price * 100

        # 고정 손절
        if pnl_pct <= self.stop_loss_pct:
            logger.warning(
                "손절 트리거: %s 손익률 %.2f%% <= %.2f%%",
                symbol, pnl_pct, self.stop_loss_pct,
            )
            with self._trailing_lock:
                self._trailing_highs.pop(symbol, None)
            return "stop_loss"

        # 고정 익절
        if pnl_pct >= self.take_profit_pct:
            logger.info(
                "익절 트리거: %s 손익률 %.2f%% >= %.2f%%",
                symbol, pnl_pct, self.take_profit_pct,
            )
            with self._trailing_lock:
                self._trailing_highs.pop(symbol, None)
            return "take_profit"

        # 트레일링 스톱 (활성화 시)
        if self.trailing_stop_pct > 0:
            with self._trailing_lock:
                prev_high = self._trailing_highs.get(symbol)
                if prev_high is None:
                    self._trailing_highs[symbol] = current_price
                    prev_high = current_price
                elif current_price > prev_high:
                    self._trailing_highs[symbol] = current_price
                    prev_high = current_price

            drop_from_high = (current_price - prev_high) / prev_high * 100
            if drop_from_high <= -self.trailing_stop_pct and pnl_pct > 0:
                logger.warning(
                    "트레일링 스톱: %s 고점 대비 %.2f%% 하락 (기준: -%.2f%%)",
                    symbol, drop_from_high, self.trailing_stop_pct,
                )
                with self._trailing_lock:
                    self._trailing_highs.pop(symbol, None)
                return "trailing_stop"

        return None

    def reset_trailing(self, symbol: str):
        """포지션 청산 시 트레일링 고점 초기화."""
        with self._trailing_lock:
            self._trailing_highs.pop(symbol, None)
