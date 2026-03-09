"""StrategyArena 테스트"""

import pytest

from cryptolight.evaluation.arena import StrategyArena, STRATEGY_NAMES
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


def test_compete_default_strategies():
    arena = StrategyArena(n_folds=2)
    candles = _make_candles(300)
    results = arena.compete(candles)
    assert len(results) > 0
    # 순위가 부여되어야 함
    for r in results:
        assert "rank" in r
        assert "strategy" in r


def test_compete_custom_configs():
    arena = StrategyArena(n_folds=2)
    candles = _make_candles(300)
    configs = [
        {"name": "rsi", "params": {"period": 14}},
        {"name": "macd", "params": {}},
    ]
    results = arena.compete(candles, strategy_configs=configs)
    assert len(results) == 2
    assert results[0]["rank"] == 1
    assert results[1]["rank"] == 2


def test_compete_sorted_by_sharpe():
    arena = StrategyArena(n_folds=2)
    candles = _make_candles(300)
    results = arena.compete(candles)
    sharpes = [r.get("sharpe", -999) for r in results]
    assert sharpes == sorted(sharpes, reverse=True)


def test_compete_insufficient_data():
    arena = StrategyArena(n_folds=2)
    candles = _make_candles(2)  # 극단적으로 적은 데이터
    results = arena.compete(candles)
    for r in results:
        assert r["status"] == "insufficient_data"


def test_summary_text():
    arena = StrategyArena(n_folds=2)
    candles = _make_candles(300)
    results = arena.compete(candles)
    text = arena.summary_text(results)
    assert "Strategy Arena" in text


def test_summary_text_empty():
    arena = StrategyArena()
    text = arena.summary_text([])
    assert "결과 없음" in text


def test_wf_passed_field():
    arena = StrategyArena(n_folds=2, min_wf_consistency=0.0)
    candles = _make_candles(300)
    results = arena.compete(candles)
    for r in results:
        if r["status"] == "evaluated":
            assert "wf_passed" in r
            assert isinstance(r["wf_passed"], bool)


def test_calc_sharpe_low_trades():
    arena = StrategyArena()
    # 모의 결과 객체
    class MockResult:
        total_trades = 1
        total_return_pct = 5.0
    assert arena._calc_sharpe_from_result(MockResult()) == 0.0


def test_calc_sharpe_normal():
    arena = StrategyArena()
    class MockResult:
        total_trades = 10
        total_return_pct = 15.0
    sharpe = arena._calc_sharpe_from_result(MockResult())
    assert sharpe > 0
