from datetime import datetime, timezone

import cryptolight.main as main_module
from cryptolight.config.settings import Settings
from cryptolight.storage.repository import TradeRepository


def test_repository_parameter_adjustments_roundtrip(tmp_path):
    repo = TradeRepository(db_path=tmp_path / "test.db")

    changed = repo.apply_parameter_adjustments(
        strategy="score",
        new_params={"rsi_oversold": 33, "bb_std_mult": 2.2},
        reason="test",
        metric_summary="Sharpe 0.2 -> 0.6",
        explanations={
            "rsi_oversold": "더 많이 눌렸을 때만 매수하게 됩니다",
            "bb_std_mult": "밴드 폭을 넓혀 더 신중하게 봅니다",
        },
        previous_params={"rsi_oversold": 35, "bb_std_mult": 2.0},
    )

    current = repo.get_strategy_parameters("score")
    history = repo.get_recent_parameter_adjustments(limit=5, strategy="score")

    assert len(changed) == 2
    assert current["rsi_oversold"] == 33
    assert current["bb_std_mult"] == 2.2
    assert history[0]["strategy"] == "score"
    assert history[0]["metric_summary"] == "Sharpe 0.2 -> 0.6"
    repo.close()


def test_latest_parameter_adjustment_returns_most_recent(tmp_path):
    repo = TradeRepository(db_path=tmp_path / "test.db")
    repo.apply_parameter_adjustments(
        strategy="score",
        new_params={"rsi_oversold": 34},
        reason="first",
        previous_params={"rsi_oversold": 35},
    )
    repo.apply_parameter_adjustments(
        strategy="score",
        new_params={"rsi_oversold": 33},
        reason="second",
        previous_params={"rsi_oversold": 34},
    )

    latest = repo.get_latest_parameter_adjustment("score")

    assert latest is not None
    assert latest["new_value"] == 33
    assert latest["reason"] == "second"
    repo.close()


def test_score_criteria_reflects_tuned_parameters():
    original_name = main_module._active_strategy_name
    original_params = dict(main_module._active_strategy_params)
    original_snapshots = dict(main_module._market_snapshots)

    try:
        main_module._active_strategy_name = "score"
        main_module._active_strategy_params = {
            "rsi_oversold": 33,
            "rsi_overbought": 68,
            "bb_std_mult": 2.3,
            "volume_period": 24,
        }
        main_module._market_snapshots.clear()
        main_module._market_snapshots.update({"KRW-BTC": {"regime": "volatile"}})

        settings = Settings(_env_file=None, strategy_name="score")
        text = "\n".join(main_module._build_strategy_criteria_lines(settings))

        assert "RSI<=33" in text
        assert "RSI>=68" in text
        assert "표준편차 2.30" in text
        assert "거래량 기간 24" in text
        assert "자동 조정값" in text
    finally:
        main_module._active_strategy_name = original_name
        main_module._active_strategy_params = original_params
        main_module._market_snapshots.clear()
        main_module._market_snapshots.update(original_snapshots)


def test_tuning_history_lines_include_beginner_explanations(tmp_path):
    repo = TradeRepository(db_path=tmp_path / "test.db")
    repo.apply_parameter_adjustments(
        strategy="score",
        new_params={"rsi_oversold": 33},
        reason="test",
        metric_summary="Sharpe 0.2 -> 0.6",
        explanations={"rsi_oversold": "더 많이 눌렸을 때만 매수하게 됩니다"},
        previous_params={"rsi_oversold": 35},
    )

    original_name = main_module._active_strategy_name
    original_params = dict(main_module._active_strategy_params)
    try:
        main_module._active_strategy_name = "score"
        main_module._active_strategy_params = {"rsi_oversold": 33}

        settings = Settings(_env_file=None, strategy_name="score")
        text = "\n".join(main_module._build_tuning_history_lines(repo, settings))

        assert "최근 자동 조정:" in text
        assert "RSI 과매도 기준: 35 -> 33" in text
        assert "설명: 더 많이 눌렸을 때만 매수하게 됩니다" in text
        assert "근거: Sharpe 0.2 -> 0.6" in text
    finally:
        main_module._active_strategy_name = original_name
        main_module._active_strategy_params = original_params
        main_module._scheduler = None
        repo.close()


def test_tuning_history_lines_include_next_run_and_cooldown(tmp_path):
    class _FakeJob:
        next_run_time = datetime(2026, 3, 12, 0, 0, 0, tzinfo=timezone.utc)

    class _FakeScheduler:
        def get_job(self, job_id):
            assert job_id == "parameter_tuning"
            return _FakeJob()

    repo = TradeRepository(db_path=tmp_path / "test.db")
    repo.apply_parameter_adjustments(
        strategy="score",
        new_params={"rsi_oversold": 33},
        reason="test",
        metric_summary="Sharpe 0.2 -> 0.6",
        explanations={"rsi_oversold": "더 많이 눌렸을 때만 매수하게 됩니다"},
        previous_params={"rsi_oversold": 35},
    )

    original_name = main_module._active_strategy_name
    original_params = dict(main_module._active_strategy_params)
    original_scheduler = main_module._scheduler
    try:
        main_module._active_strategy_name = "score"
        main_module._active_strategy_params = {"rsi_oversold": 33}
        main_module._scheduler = _FakeScheduler()

        settings = Settings(_env_file=None, strategy_name="score", parameter_tuning_cooldown_hours=12)
        text = "\n".join(main_module._build_tuning_history_lines(repo, settings))

        assert "다음 자동조정:" in text
        assert "2026-03-12 09:00 KST" in text
        assert "조정 쿨다운: 12시간" in text
        assert "남은 쿨다운:" in text
    finally:
        main_module._active_strategy_name = original_name
        main_module._active_strategy_params = original_params
        main_module._scheduler = original_scheduler
        repo.close()


def test_run_parameter_tuning_skips_when_in_cooldown(tmp_path):
    repo = TradeRepository(db_path=tmp_path / "test.db")
    repo.apply_parameter_adjustments(
        strategy="score",
        new_params={"rsi_oversold": 34},
        reason="first",
        previous_params={"rsi_oversold": 35},
    )

    settings = Settings(
        _env_file=None,
        strategy_name="score",
        parameter_tuning_cooldown_hours=24,
    )
    result = main_module._run_parameter_tuning(
        repo=repo,
        settings=settings,
        strategy_name="score",
        candles=[],
        bot=None,
    )

    assert result["applied"] is False
    assert "쿨다운" in result["summary"]
    repo.close()
