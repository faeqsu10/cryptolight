"""이상 거래 감지 — 주문 빈도 제한, 쿨다운"""

import logging
import time

logger = logging.getLogger("cryptolight.risk.cooldown")


class TradeCooldown:
    """동일 종목에 대한 연속 주문을 제한한다."""

    def __init__(self, cooldown_seconds: int = 300, max_orders_per_hour: int = 10):
        self._cooldown_seconds = cooldown_seconds
        self._max_orders_per_hour = max_orders_per_hour
        self._last_order_time: dict[str, float] = {}  # symbol → timestamp
        self._order_history: list[float] = []  # 전체 주문 타임스탬프

    def can_trade(self, symbol: str) -> tuple[bool, str]:
        """주문 가능 여부를 확인한다."""
        now = time.time()

        # 종목별 쿨다운
        last = self._last_order_time.get(symbol, 0)
        elapsed = now - last
        if elapsed < self._cooldown_seconds:
            remaining = int(self._cooldown_seconds - elapsed)
            reason = f"쿨다운 중: {symbol} ({remaining}초 남음)"
            logger.info(reason)
            return False, reason

        # 시간당 주문 횟수 제한
        one_hour_ago = now - 3600
        self._order_history = [t for t in self._order_history if t > one_hour_ago]
        if len(self._order_history) >= self._max_orders_per_hour:
            reason = f"시간당 주문 한도 도달: {len(self._order_history)}/{self._max_orders_per_hour}"
            logger.warning(reason)
            return False, reason

        return True, ""

    def record_trade(self, symbol: str):
        """주문 실행을 기록한다."""
        now = time.time()
        self._last_order_time[symbol] = now
        self._order_history.append(now)
