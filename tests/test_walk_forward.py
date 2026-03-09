"""WalkForwardValidator 테스트"""
import pytest

from cryptolight.backtest.walk_forward import WalkForwardValidator
from cryptolight.exchange.base import Candle
from cryptolight.strategy.base import BaseStrategy, Signal


class SimpleBuySellStrategy(BaseStrategy):
    def __init__(self):
        self._n = 0
    def analyze(self, candles):
        self._n += 1
        action = "buy" if self._n % 3 == 1 else ("sell" if self._n % 3 == 0 else "hold")
        return Signal(action=action, symbol="T", reason="test", confidence=0.8)
    def required_candle_count(self):
        return 5


def _make_candles(n: int = 200) -> list[Candle]:
    return [
        Candle(timestamp=f"2024-{(i//28)+1:02d}-{(i%28)+1:02d}",
               open=50000 + i*50, high=50000 + i*50 + 300,
               low=50000 + i*50 - 200, close=50000 + i*50 + 100, volume=100)
        for i in range(n)
    ]


def test_walk_forward_runs():
    validator = WalkForwardValidator(SimpleBuySellStrategy(), order_amount=50_000)
    result = validator.run(_make_candles(200), n_folds=3)
    assert len(result.folds) > 0


def test_walk_forward_has_metrics():
    validator = WalkForwardValidator(SimpleBuySellStrategy(), order_amount=50_000)
    result = validator.run(_make_candles(200), n_folds=3)
    assert result.avg_in_sample_return is not None
    assert result.avg_out_sample_return is not None
    assert result.consistency >= 0


def test_walk_forward_summary():
    validator = WalkForwardValidator(SimpleBuySellStrategy(), order_amount=50_000)
    result = validator.run(_make_candles(200), n_folds=3)
    text = result.summary_text()
    assert "Walk-Forward" in text
    assert "Fold" in text


def test_insufficient_data():
    validator = WalkForwardValidator(SimpleBuySellStrategy(), order_amount=50_000)
    result = validator.run(_make_candles(10), n_folds=5)
    assert len(result.folds) == 0


def test_invalid_n_folds():
    validator = WalkForwardValidator(SimpleBuySellStrategy(), order_amount=50_000)
    with pytest.raises(ValueError, match="n_folds must be >= 2"):
        validator.run(_make_candles(200), n_folds=1)
    with pytest.raises(ValueError, match="n_folds must be >= 2"):
        validator.run(_make_candles(200), n_folds=0)
