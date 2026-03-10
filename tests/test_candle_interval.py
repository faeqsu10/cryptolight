"""분봉 캔들 인터벌 설정 테스트"""

import pytest
from unittest.mock import MagicMock, patch

from cryptolight.config.settings import Settings


class TestCandleIntervalSetting:
    def test_default_is_minute240(self):
        s = Settings(upbit_access_key="x", upbit_secret_key="x")
        assert s.candle_interval == "minute240"

    def test_can_set_day(self):
        s = Settings(upbit_access_key="x", upbit_secret_key="x", candle_interval="day")
        assert s.candle_interval == "day"

    def test_can_set_minute60(self):
        s = Settings(upbit_access_key="x", upbit_secret_key="x", candle_interval="minute60")
        assert s.candle_interval == "minute60"

    def test_can_set_minute5(self):
        s = Settings(upbit_access_key="x", upbit_secret_key="x", candle_interval="minute5")
        assert s.candle_interval == "minute5"


class TestAutoSelectSymbolsSetting:
    def test_default_false(self):
        s = Settings(upbit_access_key="x", upbit_secret_key="x")
        assert s.auto_select_symbols is False

    def test_screening_defaults(self):
        s = Settings(upbit_access_key="x", upbit_secret_key="x")
        assert s.top_volume_limit == 10
        assert s.min_daily_volume_krw == 10_000_000_000
        assert s.min_backtest_sharpe == 0.0
        assert s.max_correlation == 0.9

    def test_custom_screening_values(self):
        s = Settings(
            upbit_access_key="x", upbit_secret_key="x",
            auto_select_symbols=True,
            top_volume_limit=20,
            min_daily_volume_krw=5_000_000_000,
            min_backtest_sharpe=0.5,
            max_correlation=0.8,
        )
        assert s.auto_select_symbols is True
        assert s.top_volume_limit == 20
        assert s.min_daily_volume_krw == 5_000_000_000
        assert s.min_backtest_sharpe == 0.5
        assert s.max_correlation == 0.8
