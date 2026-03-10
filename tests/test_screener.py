"""종목 자동 스크리닝 파이프라인 테스트"""

import pytest

from cryptolight.exchange.base import Candle
from cryptolight.market.screener import (
    ScreeningResult,
    backtest_filter,
    calculate_returns,
    correlation_filter,
    pearson_correlation,
    run_screening_pipeline,
)


def _make_candles(prices: list[float], volume: float = 100.0) -> list[Candle]:
    """테스트용 캔들 생성."""
    return [
        Candle(
            timestamp=f"2025-01-{i+1:02d}T00:00:00",
            open=p * 0.99,
            high=p * 1.01,
            low=p * 0.98,
            close=p,
            volume=volume,
        )
        for i, p in enumerate(prices)
    ]


def _trending_up_prices(n: int = 100, start: float = 50000) -> list[float]:
    """꾸준히 상승하는 가격 시리즈."""
    return [start * (1 + 0.005 * i) for i in range(n)]


def _flat_prices(n: int = 100, base: float = 50000) -> list[float]:
    """변동이 거의 없는 가격 시리즈."""
    import math
    return [base + math.sin(i * 0.1) * 100 for i in range(n)]


class TestCalculateReturns:
    def test_basic_returns(self):
        candles = _make_candles([100, 110, 105])
        rets = calculate_returns(candles)
        assert len(rets) == 2
        assert abs(rets[0] - 0.1) < 1e-10  # 100 → 110 = +10%

    def test_empty_candles(self):
        assert calculate_returns([]) == []

    def test_single_candle(self):
        assert calculate_returns(_make_candles([100])) == []


class TestPearsonCorrelation:
    def test_perfect_positive(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.0, 4.0, 6.0, 8.0, 10.0]
        assert abs(pearson_correlation(x, y) - 1.0) < 1e-10

    def test_perfect_negative(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [10.0, 8.0, 6.0, 4.0, 2.0]
        assert abs(pearson_correlation(x, y) + 1.0) < 1e-10

    def test_uncorrelated(self):
        x = [1.0, -1.0, 1.0, -1.0, 1.0]
        y = [1.0, 1.0, -1.0, -1.0, 1.0]
        corr = pearson_correlation(x, y)
        assert abs(corr) < 0.5  # 낮은 상관관계

    def test_short_series_returns_zero(self):
        assert pearson_correlation([1.0], [2.0]) == 0.0

    def test_different_lengths(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        y = [2.0, 4.0, 6.0, 8.0, 10.0]
        corr = pearson_correlation(x, y)
        assert abs(corr - 1.0) < 1e-10  # 뒤쪽 5개를 사용


class TestBacktestFilter:
    def test_trending_up_passes(self):
        """상승 추세 종목은 Sharpe >= 0으로 통과해야 한다."""
        prices = _trending_up_prices(100)
        candles = _make_candles(prices)
        passed, details = backtest_filter(
            {"KRW-BTC": candles},
            strategy_name="score",
            min_sharpe=-999,  # 무조건 통과
        )
        assert "KRW-BTC" in passed
        assert "KRW-BTC" in details

    def test_insufficient_candles_skipped(self):
        """캔들 부족 시 스킵."""
        candles = _make_candles([100, 110, 105])
        passed, details = backtest_filter({"KRW-BTC": candles})
        assert "KRW-BTC" not in passed
        assert details["KRW-BTC"]["skipped"] is True

    def test_high_sharpe_threshold_filters(self):
        """높은 Sharpe 임계값은 대부분 필터링."""
        prices = _flat_prices(100)
        candles = _make_candles(prices)
        passed, details = backtest_filter(
            {"KRW-BTC": candles},
            min_sharpe=100.0,  # 비현실적으로 높은 기준
        )
        assert "KRW-BTC" not in passed


class TestCorrelationFilter:
    def test_uncorrelated_symbols_kept(self):
        """상관관계가 낮은 종목들은 모두 유지."""
        candles = {
            "KRW-BTC": _make_candles(_trending_up_prices(50)),
            "KRW-ETH": _make_candles(_flat_prices(50)),
        }
        selected, removed = correlation_filter(
            ["KRW-BTC", "KRW-ETH"],
            candles,
            max_correlation=0.9,
        )
        assert len(selected) == 2
        assert len(removed) == 0

    def test_highly_correlated_removes_lower_volume(self):
        """높은 상관관계 쌍에서 거래량 낮은 종목 제외."""
        # 동일한 가격 패턴 = 상관관계 1.0
        prices = _trending_up_prices(50)
        candles = {
            "KRW-BTC": _make_candles(prices),
            "KRW-ETH": _make_candles(prices),  # 동일 패턴
        }
        volume_ranking = {"KRW-BTC": 1000, "KRW-ETH": 500}
        selected, removed = correlation_filter(
            ["KRW-BTC", "KRW-ETH"],
            candles,
            max_correlation=0.9,
            volume_ranking=volume_ranking,
        )
        assert "KRW-BTC" in selected  # 거래량 높은 쪽 유지
        assert "KRW-ETH" in removed  # 거래량 낮은 쪽 제거

    def test_max_positions_limit(self):
        """max_positions 이상으로 선정하지 않음."""
        candles = {
            f"KRW-COIN{i}": _make_candles(_flat_prices(50, base=10000 + i * 1000))
            for i in range(10)
        }
        symbols = list(candles.keys())
        selected, _ = correlation_filter(
            symbols, candles, max_correlation=0.99, max_positions=3,
        )
        assert len(selected) <= 3

    def test_single_symbol(self):
        """종목 1개는 그대로 반환."""
        candles = {"KRW-BTC": _make_candles([100, 110])}
        selected, removed = correlation_filter(["KRW-BTC"], candles, max_positions=5)
        assert selected == ["KRW-BTC"]
        assert removed == []

    def test_empty_symbols(self):
        """빈 리스트 입력 시 빈 결과."""
        selected, removed = correlation_filter([], {}, max_positions=5)
        assert selected == []
        assert removed == []


class TestScreeningResult:
    def test_dataclass(self):
        result = ScreeningResult(
            selected=["KRW-BTC"],
            candidates=["KRW-BTC", "KRW-ETH"],
            backtest_passed=["KRW-BTC"],
            backtest_details={"KRW-BTC": {"sharpe": 0.5}},
            correlation_removed=["KRW-ETH"],
        )
        assert result.selected == ["KRW-BTC"]
        assert len(result.candidates) == 2


class TestRunScreeningPipeline:
    def test_pipeline_with_mock_client(self):
        """모킹된 클라이언트로 전체 파이프라인 테스트."""

        class MockClient:
            def get_top_volume_symbols(self, quote="KRW", limit=10, min_volume_krw=0):
                return ["KRW-BTC", "KRW-ETH"]

            def get_candles(self, symbol, interval="day", count=200):
                prices = _trending_up_prices(count)
                return _make_candles(prices)

        result = run_screening_pipeline(
            client=MockClient(),
            strategy_name="score",
            top_limit=10,
            min_volume_krw=0,
            min_sharpe=-999,
            max_correlation=0.99,
            max_positions=5,
        )
        assert isinstance(result, ScreeningResult)
        assert len(result.candidates) == 2

    def test_pipeline_empty_candidates(self):
        """후보가 없을 때 빈 결과."""

        class MockClient:
            def get_top_volume_symbols(self, **kwargs):
                return []

        result = run_screening_pipeline(client=MockClient())
        assert result.selected == []
        assert result.candidates == []
