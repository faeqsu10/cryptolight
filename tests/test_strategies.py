"""전략 테스트"""
from cryptolight.exchange.base import Candle
from cryptolight.strategy import create_strategy
from cryptolight.strategy.rsi import RSIStrategy
from cryptolight.strategy.macd import MACDStrategy
from cryptolight.strategy.bollinger import BollingerStrategy
from cryptolight.strategy.volatility_breakout import VolatilityBreakoutStrategy
from cryptolight.strategy.ensemble import EnsembleStrategy


def _rising_candles(n: int = 50, base: float = 50000) -> list[Candle]:
    """상승 추세 캔들."""
    return [
        Candle(timestamp=f"2024-01-{i+1:02d}", open=base + i*500,
               high=base + i*500 + 300, low=base + i*500 - 100,
               close=base + i*500 + 200, volume=100 + i*10)
        for i in range(n)
    ]


def _falling_candles(n: int = 50, base: float = 70000) -> list[Candle]:
    """하락 추세 캔들."""
    return [
        Candle(timestamp=f"2024-01-{i+1:02d}", open=base - i*500,
               high=base - i*500 + 100, low=base - i*500 - 300,
               close=base - i*500 - 200, volume=100 + i*10)
        for i in range(n)
    ]


def test_rsi_strategy():
    strategy = RSIStrategy()
    assert strategy.required_candle_count() >= 14
    signal = strategy.analyze(_rising_candles())
    assert signal.action in ("buy", "sell", "hold")
    assert "rsi" in signal.indicators


def test_macd_strategy():
    strategy = MACDStrategy()
    assert strategy.required_candle_count() >= 26
    signal = strategy.analyze(_rising_candles())
    assert signal.action in ("buy", "sell", "hold")
    assert "macd" in signal.indicators


def test_bollinger_strategy():
    strategy = BollingerStrategy()
    assert strategy.required_candle_count() >= 20
    signal = strategy.analyze(_rising_candles())
    assert signal.action in ("buy", "sell", "hold")
    assert "pct_b" in signal.indicators


def test_volatility_breakout_strategy():
    strategy = VolatilityBreakoutStrategy()
    signal = strategy.analyze(_rising_candles())
    assert signal.action in ("buy", "sell", "hold")


def test_ensemble_strategy():
    strategy = create_strategy("ensemble", strategy_names=["rsi", "macd", "bollinger"])
    signal = strategy.analyze(_rising_candles())
    assert signal.action in ("buy", "sell", "hold")


def test_create_strategy_factory():
    for name in ("rsi", "macd", "bollinger", "volatility_breakout"):
        s = create_strategy(name)
        assert s is not None

    ens = create_strategy("ensemble", strategy_names=["rsi", "macd"])
    assert isinstance(ens, EnsembleStrategy)
