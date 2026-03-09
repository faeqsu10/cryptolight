"""AdaptiveController 테스트"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from cryptolight.evaluation.controller import AdaptiveController
from cryptolight.evaluation.performance import PerformanceEvaluator


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.get_strategy_switches.return_value = []
    return repo


@pytest.fixture
def controller(mock_repo):
    return AdaptiveController(
        repo=mock_repo,
        min_sharpe_improvement=0.5,
        cooldown_days=7,
        rollback_loss_threshold=-5.0,
    )


@pytest.fixture
def mock_evaluator():
    evaluator = MagicMock(spec=PerformanceEvaluator)
    return evaluator


def test_should_switch_no_candidates(controller, mock_evaluator):
    mock_evaluator.evaluate_strategy.return_value = {"sharpe_ratio": 0.5}
    result = controller.should_switch("rsi", [], mock_evaluator)
    assert result["switch"] is False
    assert "대안 전략 없음" in result["reason"]


def test_should_switch_in_cooldown(controller, mock_repo, mock_evaluator):
    # 최근 전환 기록 → 쿨다운
    mock_repo.get_strategy_switches.return_value = [
        {"switched_at": datetime.now().isoformat(), "from_strategy": "rsi", "to_strategy": "macd"}
    ]
    result = controller.should_switch("macd", [], mock_evaluator)
    assert result["switch"] is False
    assert "쿨다운" in result["reason"]


def test_should_switch_current_good(controller, mock_evaluator):
    mock_evaluator.evaluate_strategy.return_value = {"sharpe_ratio": 1.5}
    arena_results = [
        {"strategy": "macd", "sharpe": 2.0, "wf_passed": True, "params": {}},
    ]
    result = controller.should_switch("rsi", arena_results, mock_evaluator)
    assert result["switch"] is False
    assert "양호" in result["reason"]


def test_should_switch_triggers(controller, mock_evaluator):
    # 현재 전략 부진 + 대안 우수
    mock_evaluator.evaluate_strategy.return_value = {"sharpe_ratio": -0.5}
    arena_results = [
        {"strategy": "macd", "sharpe": 1.0, "wf_passed": True, "params": {"fast": 12}},
    ]
    result = controller.should_switch("rsi", arena_results, mock_evaluator)
    assert result["switch"] is True
    assert result["to"] == "macd"
    assert result["to_params"] == {"fast": 12}


def test_should_switch_insufficient_improvement(controller, mock_evaluator):
    # 현재 부진하지만 개선폭 부족
    mock_evaluator.evaluate_strategy.return_value = {"sharpe_ratio": -0.1}
    arena_results = [
        {"strategy": "macd", "sharpe": 0.1, "wf_passed": True, "params": {}},
    ]
    result = controller.should_switch("rsi", arena_results, mock_evaluator)
    assert result["switch"] is False
    assert "개선폭 부족" in result["reason"]


def test_should_switch_wf_not_passed(controller, mock_evaluator):
    mock_evaluator.evaluate_strategy.return_value = {"sharpe_ratio": -1.0}
    arena_results = [
        {"strategy": "macd", "sharpe": 2.0, "wf_passed": False, "params": {}},
    ]
    result = controller.should_switch("rsi", arena_results, mock_evaluator)
    assert result["switch"] is False
    assert "대안 전략 없음" in result["reason"]


def test_record_switch(controller, mock_repo):
    controller.record_switch("rsi", "macd", "테스트 전환")
    mock_repo.record_strategy_switch.assert_called_once_with("rsi", "macd", "테스트 전환")


def test_get_switch_history(controller, mock_repo):
    mock_repo.get_strategy_switches.return_value = [
        {"from_strategy": "rsi", "to_strategy": "macd", "switched_at": "2024-01-01", "reason": "test"}
    ]
    history = controller.get_switch_history(limit=5)
    assert len(history) == 1
    mock_repo.get_strategy_switches.assert_called_with(5)


def test_check_rollback_no_history(controller, mock_repo, mock_evaluator):
    mock_repo.get_strategy_switches.return_value = []
    result = controller.check_rollback("macd", mock_evaluator)
    assert result is None


def test_check_rollback_too_old(controller, mock_repo, mock_evaluator):
    old_date = (datetime.now() - timedelta(days=5)).isoformat()
    mock_repo.get_strategy_switches.return_value = [
        {"switched_at": old_date, "from_strategy": "rsi", "to_strategy": "macd"}
    ]
    result = controller.check_rollback("macd", mock_evaluator)
    assert result is None


def test_check_rollback_triggers(controller, mock_repo, mock_evaluator):
    recent = (datetime.now() - timedelta(days=1)).isoformat()
    mock_repo.get_strategy_switches.return_value = [
        {"switched_at": recent, "from_strategy": "rsi", "to_strategy": "macd"}
    ]
    mock_evaluator.evaluate_strategy.return_value = {
        "status": "evaluated",
        "total_return_pct": -8.0,
    }
    result = controller.check_rollback("macd", mock_evaluator)
    assert result is not None
    assert result["rollback"] is True
    assert result["to"] == "rsi"


def test_check_rollback_ok(controller, mock_repo, mock_evaluator):
    recent = (datetime.now() - timedelta(days=1)).isoformat()
    mock_repo.get_strategy_switches.return_value = [
        {"switched_at": recent, "from_strategy": "rsi", "to_strategy": "macd"}
    ]
    mock_evaluator.evaluate_strategy.return_value = {
        "status": "evaluated",
        "total_return_pct": 2.0,
    }
    result = controller.check_rollback("macd", mock_evaluator)
    assert result is None


def test_check_rollback_insufficient_data(controller, mock_repo, mock_evaluator):
    recent = (datetime.now() - timedelta(days=1)).isoformat()
    mock_repo.get_strategy_switches.return_value = [
        {"switched_at": recent, "from_strategy": "rsi", "to_strategy": "macd"}
    ]
    mock_evaluator.evaluate_strategy.return_value = {"status": "insufficient_data"}
    result = controller.check_rollback("macd", mock_evaluator)
    assert result is None
