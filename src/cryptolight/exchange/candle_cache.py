"""캔들 캐시 — 동일 심볼/인터벌의 중복 API 호출 방지"""

import logging
import time

from cryptolight.exchange.base import Candle

logger = logging.getLogger("cryptolight.exchange.cache")


class CandleCache:
    """심볼별 캔들 데이터를 TTL 기반으로 캐시한다."""

    def __init__(self, ttl_seconds: int = 60):
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, list[Candle]]] = {}

    def get(self, key: str) -> list[Candle] | None:
        """캐시에서 캔들을 가져온다. 만료 시 None."""
        if key not in self._cache:
            return None
        ts, candles = self._cache[key]
        if time.time() - ts > self._ttl:
            del self._cache[key]
            return None
        logger.debug("캔들 캐시 히트: %s (%d개)", key, len(candles))
        return candles

    def put(self, key: str, candles: list[Candle]):
        """캔들을 캐시에 저장한다."""
        self._cache[key] = (time.time(), candles)

    def make_key(self, symbol: str, interval: str, count: int) -> str:
        return f"{symbol}:{interval}:{count}"

    def clear(self):
        self._cache.clear()

    def size(self) -> int:
        return len(self._cache)
