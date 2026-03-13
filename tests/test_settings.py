"""Settings 설정 검증 테스트"""
import pytest
from pydantic import ValidationError

from cryptolight.config.settings import Settings


def test_default_settings(monkeypatch):
    monkeypatch.delenv("TRAILING_STOP_PCT", raising=False)
    monkeypatch.delenv("TAKE_PROFIT_PCT", raising=False)
    monkeypatch.delenv("CANDLE_INTERVAL", raising=False)
    monkeypatch.delenv("AUTO_SELECT_SYMBOLS", raising=False)
    s = Settings(_env_file=None)
    assert s.trade_mode == "paper"
    assert s.max_order_amount_krw == 50_000
    assert s.absolute_max_order_krw == 500_000
    assert s.trailing_stop_pct == 0.0
    assert s.backtest_slippage_pct == 0.1
    assert s.backtest_spread_pct == 0.05
    assert s.log_file == ""
    assert s.telegram_poll_timeout_seconds == 20
    assert s.telegram_request_timeout_seconds == 30
    assert s.telegram_poll_backoff_initial_seconds == 1.0
    assert s.telegram_poll_backoff_max_seconds == 30.0
    assert s.app_timezone == "Asia/Seoul"
    assert s.daily_summary_hour == 9
    assert s.daily_summary_minute == 0
    assert s.self_improvement_day_of_week == "sun"
    assert s.self_improvement_hour == 3
    assert s.self_improvement_minute == 0
    assert s.enable_auto_parameter_tuning is True
    assert s.parameter_tuning_interval_hours == 6
    assert s.parameter_tuning_cooldown_hours == 12
    assert s.parameter_tuning_lookback_candles == 300
    assert s.parameter_tuning_n_folds == 3
    assert s.parameter_tuning_min_wf_consistency == 66.7


def test_trade_mode_validation():
    with pytest.raises(ValidationError):
        Settings(trade_mode="invalid")


def test_trade_mode_paper():
    s = Settings(trade_mode="paper")
    assert s.trade_mode == "paper"


def test_trade_mode_live():
    s = Settings(trade_mode="live")
    assert s.trade_mode == "live"


def test_symbol_list():
    s = Settings(target_symbols="KRW-BTC,KRW-ETH,KRW-XRP")
    assert s.symbol_list == ["KRW-BTC", "KRW-ETH", "KRW-XRP"]


def test_ensemble_strategy_list():
    s = Settings(ensemble_strategies="rsi,macd")
    assert s.ensemble_strategy_list == ["rsi", "macd"]
