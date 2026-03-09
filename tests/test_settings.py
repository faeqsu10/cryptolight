"""Settings 설정 검증 테스트"""
import pytest
from pydantic import ValidationError

from cryptolight.config.settings import Settings


def test_default_settings():
    s = Settings()
    assert s.trade_mode == "paper"
    assert s.max_order_amount_krw == 50_000
    assert s.absolute_max_order_krw == 500_000
    assert s.trailing_stop_pct == 0.0
    assert s.backtest_slippage_pct == 0.1
    assert s.backtest_spread_pct == 0.05
    assert s.log_file == ""


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
