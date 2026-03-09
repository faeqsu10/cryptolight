"""CandleCache 캔들 캐시 테스트"""
import time

from cryptolight.exchange.base import Candle
from cryptolight.exchange.candle_cache import CandleCache


def _candle():
    return Candle(timestamp="2024-01-01", open=100, high=110, low=90, close=105, volume=50)


def test_put_and_get():
    cache = CandleCache(ttl_seconds=60)
    candles = [_candle()]
    cache.put("BTC:day:50", candles)
    result = cache.get("BTC:day:50")
    assert result is not None
    assert len(result) == 1


def test_miss():
    cache = CandleCache(ttl_seconds=60)
    assert cache.get("MISSING") is None


def test_ttl_expiry():
    cache = CandleCache(ttl_seconds=0)  # 즉시 만료
    cache.put("BTC:day:50", [_candle()])
    time.sleep(0.01)
    assert cache.get("BTC:day:50") is None


def test_make_key():
    cache = CandleCache()
    key = cache.make_key("KRW-BTC", "day", 200)
    assert key == "KRW-BTC:day:200"


def test_clear():
    cache = CandleCache()
    cache.put("a", [_candle()])
    cache.put("b", [_candle()])
    assert cache.size() == 2
    cache.clear()
    assert cache.size() == 0
