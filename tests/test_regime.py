"""MarketRegime 시장 국면 감지 테스트"""
from cryptolight.exchange.base import Candle
from cryptolight.market.regime import MarketRegime


def _trending_candles(n: int = 60) -> list[Candle]:
    """강한 상승 추세."""
    return [
        Candle(timestamp=f"2024-01-{i+1:02d}", open=50000 + i*1000,
               high=50000 + i*1000 + 500, low=50000 + i*1000 - 200,
               close=50000 + i*1000 + 400, volume=100 + i*5)
        for i in range(n)
    ]


def _sideways_candles(n: int = 60) -> list[Candle]:
    """횡보 (좁은 범위)."""
    return [
        Candle(timestamp=f"2024-01-{i+1:02d}", open=50000 + (i%3)*100,
               high=50000 + (i%3)*100 + 50, low=50000 + (i%3)*100 - 50,
               close=50000 + (i%3)*100, volume=100)
        for i in range(n)
    ]


def _volatile_candles(n: int = 60) -> list[Candle]:
    """높은 변동성."""
    import math
    return [
        Candle(timestamp=f"2024-01-{i+1:02d}",
               open=50000 + int(math.sin(i) * 5000),
               high=50000 + int(math.sin(i) * 5000) + 3000,
               low=50000 + int(math.sin(i) * 5000) - 3000,
               close=50000 + int(math.sin(i) * 5000) + 1000,
               volume=200 + i*10)
        for i in range(n)
    ]


def test_detect_returns_dict():
    regime = MarketRegime()
    result = regime.detect(_trending_candles())
    assert "regime" in result
    assert "adx" in result
    assert "bb_bandwidth" in result
    assert "trade_weight" in result
    assert result["regime"] in ("trending", "sideways", "volatile")


def test_trending_regime():
    regime = MarketRegime()
    result = regime.detect(_trending_candles())
    # 강한 상승 추세에서 ADX가 높아야
    assert result["adx"] > 0
    assert result["trade_weight"] > 0


def test_sideways_low_adx():
    regime = MarketRegime()
    result = regime.detect(_sideways_candles())
    # 횡보에서 ADX 낮고 trade_weight 낮아야
    assert result["trade_weight"] <= 1.0


def test_required_candle_count():
    regime = MarketRegime()
    assert regime.required_candle_count() >= 20


def test_insufficient_candles():
    regime = MarketRegime()
    short = _trending_candles(5)
    result = regime.detect(short)
    # 캔들 부족해도 크래시하지 않음
    assert result["regime"] in ("trending", "sideways", "volatile")
