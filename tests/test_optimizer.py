"""ParameterOptimizer 테스트"""

import pytest

from cryptolight.evaluation.optimizer import (
    ParameterOptimizer,
    OptimizationResult,
    PARAM_RANGES,
)
from cryptolight.exchange.base import Candle


def _make_candles(n: int = 300) -> list[Candle]:
    return [
        Candle(
            timestamp=f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
            open=50000 + i * 50,
            high=50000 + i * 50 + 300,
            low=50000 + i * 50 - 200,
            close=50000 + i * 50 + 100,
            volume=100 + i,
        )
        for i in range(n)
    ]


def test_optimize_rsi():
    optimizer = ParameterOptimizer(n_folds=2, min_wf_consistency=0.0)
    result = optimizer.optimize("rsi", _make_candles(300), n_trials=5, seed=42)
    assert isinstance(result, OptimizationResult)
    assert result.strategy == "rsi"
    assert result.trials_run == 5


def test_optimize_unknown_strategy():
    optimizer = ParameterOptimizer()
    result = optimizer.optimize("unknown_strategy", _make_candles(300), n_trials=5)
    assert result.strategy == "unknown_strategy"
    assert result.trials_run == 0
    assert result.valid_trials == 0


def test_optimize_insufficient_data():
    optimizer = ParameterOptimizer(n_folds=2)
    result = optimizer.optimize("rsi", _make_candles(5), n_trials=3, seed=42)
    assert result.valid_trials == 0


def test_param_ranges_defined():
    for strategy in ["rsi", "macd", "bollinger", "volatility_breakout"]:
        assert strategy in PARAM_RANGES
        ranges = PARAM_RANGES[strategy]
        for name, (lo, hi) in ranges.items():
            assert lo < hi, f"{strategy}.{name}: lo={lo} >= hi={hi}"


def test_sample_params():
    optimizer = ParameterOptimizer()
    params = optimizer._sample_params(PARAM_RANGES["rsi"])
    assert "period" in params
    assert "overbought" in params
    assert "oversold" in params
    assert 5 <= params["period"] <= 30
    assert 60 <= params["overbought"] <= 85


def test_optimization_result_summary():
    result = OptimizationResult(strategy="rsi")
    assert "유효한 결과 없음" in result.summary_text()

    result.valid_trials = 3
    result.trials_run = 10
    result.best_sharpe = 1.5
    result.best_return_pct = 5.0
    result.best_wf_consistency = 70.0
    result.best_params = {"period": 14}
    text = result.summary_text()
    assert "1.500" in text
    assert "5.00" in text


def test_passes_filters():
    optimizer = ParameterOptimizer(min_wf_consistency=50.0, max_overfit_ratio=3.0)

    # 통과
    assert optimizer._passes_filters({"wf_consistency": 60, "wf_overfit_ratio": 1.5})

    # consistency 부족
    assert not optimizer._passes_filters({"wf_consistency": 30, "wf_overfit_ratio": 1.5})

    # overfit 초과
    assert not optimizer._passes_filters({"wf_consistency": 60, "wf_overfit_ratio": 5.0})


def test_optimize_deterministic_with_seed():
    optimizer = ParameterOptimizer(n_folds=2, min_wf_consistency=0.0)
    candles = _make_candles(300)
    r1 = optimizer.optimize("rsi", candles, n_trials=5, seed=123)
    r2 = optimizer.optimize("rsi", candles, n_trials=5, seed=123)
    assert r1.best_params == r2.best_params
