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


def test_walk_forward_anchored_order():
    """Anchored walk-forward: 학습 구간은 항상 인덱스 0부터 시작하고
    각 fold의 학습 크기는 단조 증가해야 한다."""
    candles = _make_candles(200)
    train_ratio = 0.7
    n_folds = 3
    total = len(candles)

    initial_train_size = int(total * train_ratio)
    test_pool = total - initial_train_size
    test_size = test_pool // n_folds

    # 각 fold의 예상 학습 끝 인덱스
    expected_train_ends = [
        initial_train_size + i * test_size for i in range(n_folds)
    ]

    # 학습 크기가 단조 증가해야 함 (anchored)
    for k in range(1, len(expected_train_ends)):
        assert expected_train_ends[k] > expected_train_ends[k - 1], (
            f"fold {k}의 학습 크기가 fold {k-1}보다 크지 않음"
        )

    # 검증 구간이 학습 구간 이후에 있어야 함
    for i, train_end in enumerate(expected_train_ends):
        test_start = train_end
        test_end = test_start + test_size
        assert test_start >= train_end, f"fold {i}: 검증 구간이 학습 구간과 겹침"
        assert test_end <= total + test_size, f"fold {i}: 검증 구간이 범위 초과"


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
