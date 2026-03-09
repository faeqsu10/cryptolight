"""VolumeFilter 거래량 필터 테스트"""
from cryptolight.exchange.base import Candle
from cryptolight.strategy.base import Signal
from cryptolight.strategy.volume_filter import VolumeFilter


def _candles_with_volume(volumes: list[float]) -> list[Candle]:
    return [
        Candle(timestamp=f"2024-01-{i+1:02d}", open=50000, high=51000,
               low=49000, close=50000, volume=v)
        for i, v in enumerate(volumes)
    ]


def test_low_volume_filters_to_hold():
    vf = VolumeFilter(period=5, min_ratio=0.5)
    signal = Signal(action="buy", symbol="BTC", reason="test", confidence=0.8)
    # 평균 100, 현재 20 → ratio=0.2 < 0.5 → hold
    candles = _candles_with_volume([100, 100, 100, 100, 100, 20])
    result = vf.apply(signal, candles)
    assert result.action == "hold"


def test_normal_volume_passes():
    vf = VolumeFilter(period=5, min_ratio=0.5)
    signal = Signal(action="buy", symbol="BTC", reason="test", confidence=0.8)
    # 평균 100, 현재 80 → ratio=0.8, 통과
    candles = _candles_with_volume([100, 100, 100, 100, 100, 80])
    result = vf.apply(signal, candles)
    assert result.action == "buy"


def test_high_volume_boosts():
    vf = VolumeFilter(period=5, min_ratio=0.5, boost_ratio=2.0, boost_factor=1.2)
    signal = Signal(action="buy", symbol="BTC", reason="test", confidence=0.7)
    # 평균 100, 현재 250 → ratio=2.5 >= 2.0 → 부스트
    candles = _candles_with_volume([100, 100, 100, 100, 100, 250])
    result = vf.apply(signal, candles)
    assert result.confidence > 0.7


def test_hold_signal_not_filtered():
    vf = VolumeFilter(period=5, min_ratio=0.5)
    signal = Signal(action="hold", symbol="BTC", reason="test", confidence=0.0)
    candles = _candles_with_volume([100, 100, 100, 100, 100, 10])
    result = vf.apply(signal, candles)
    assert result.action == "hold"


def test_volume_ratio_in_indicators():
    vf = VolumeFilter(period=5)
    signal = Signal(action="buy", symbol="BTC", reason="test", confidence=0.8)
    candles = _candles_with_volume([100, 100, 100, 100, 100, 100])
    result = vf.apply(signal, candles)
    assert "volume_ratio" in result.indicators
