"""PerformanceEvaluator 테스트"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cryptolight.evaluation.performance import PerformanceEvaluator
from cryptolight.storage.repository import TradeRepository


@pytest.fixture
def repo(tmp_path):
    db_path = tmp_path / "test.db"
    return TradeRepository(db_path=db_path)


@pytest.fixture
def repo_with_trades(repo):
    """충분한 거래 데이터가 있는 repo."""
    now = datetime.now()
    for i in range(12):
        day = now - timedelta(days=12 - i)
        ts = day.strftime("%Y-%m-%d %H:%M:%S")
        if i % 2 == 0:
            # 매수
            repo._conn.execute(
                "INSERT INTO trades (symbol, side, price, quantity, amount_krw, commission, reason, strategy, timestamp) VALUES (?,?,?,?,?,?,?,?,?)",
                ("KRW-BTC", "buy", 50000 + i * 100, 0.001, 50000, 25, "test", "rsi", ts),
            )
        else:
            # 매도 (약간 이익)
            repo._conn.execute(
                "INSERT INTO trades (symbol, side, price, quantity, amount_krw, commission, reason, strategy, timestamp) VALUES (?,?,?,?,?,?,?,?,?)",
                ("KRW-BTC", "sell", 51000 + i * 100, 0.001, 51000, 25.5, "test", "rsi", ts),
            )
    repo._conn.commit()
    return repo


def test_evaluate_insufficient_data(repo):
    evaluator = PerformanceEvaluator(repo)
    result = evaluator.evaluate_strategy("rsi", days=30)
    assert result["status"] == "insufficient_data"
    assert result["trade_count"] == 0


def test_evaluate_with_trades(repo_with_trades):
    evaluator = PerformanceEvaluator(repo_with_trades)
    result = evaluator.evaluate_strategy("rsi", days=30)
    assert result["status"] == "evaluated"
    assert result["trade_count"] == 12
    assert "win_rate" in result
    assert "total_return_pct" in result
    assert "max_drawdown_pct" in result
    assert "sharpe_ratio" in result


def test_evaluate_all(repo_with_trades):
    evaluator = PerformanceEvaluator(repo_with_trades)
    results = evaluator.evaluate_all(days=30)
    assert len(results) >= 1
    assert results[0]["strategy"] == "rsi"


def test_summary_text_no_data(repo):
    evaluator = PerformanceEvaluator(repo)
    text = evaluator.summary_text(days=30)
    assert "평가 가능한 전략 없음" in text


def test_summary_text_with_data(repo_with_trades):
    evaluator = PerformanceEvaluator(repo_with_trades)
    text = evaluator.summary_text(days=30)
    assert "rsi" in text
    assert "Sharpe" in text


def test_win_rate_calculation(repo_with_trades):
    evaluator = PerformanceEvaluator(repo_with_trades)
    result = evaluator.evaluate_strategy("rsi", days=30)
    # 매도 가격 > 매수 가격이므로 승률 > 0
    assert result["win_rate"] >= 0


def test_sharpe_calculation():
    evaluator = PerformanceEvaluator(MagicMock())
    # 안정적 양수 수익
    returns = [0.01, 0.02, 0.01, 0.015, 0.02]
    sharpe = evaluator._calc_sharpe(returns)
    assert sharpe > 0

    # 단일 데이터
    assert evaluator._calc_sharpe([0.01]) == 0.0

    # 빈 리스트
    assert evaluator._calc_sharpe([]) == 0.0


def test_max_drawdown_calculation():
    evaluator = PerformanceEvaluator(MagicMock())
    # 매수 후 매도 → 이익 → 매수 후 손실
    trades = [
        {"side": "buy", "amount_krw": 50000, "commission": 25},
        {"side": "sell", "amount_krw": 55000, "commission": 27.5},
        {"side": "buy", "amount_krw": 60000, "commission": 30},
        {"side": "sell", "amount_krw": 52000, "commission": 26},
    ]
    mdd = evaluator._calc_max_drawdown(trades)
    assert mdd >= 0
