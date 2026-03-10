"""업비트 거래량 스크리닝 테스트"""

import pytest
from unittest.mock import patch, MagicMock

from cryptolight.exchange.base import Ticker
from cryptolight.exchange.upbit import UpbitClient


@pytest.fixture
def client():
    return UpbitClient(access_key="test", secret_key="test")


class TestGetMarkets:
    def test_filters_by_quote(self, client):
        mock_data = [
            {"market": "KRW-BTC", "korean_name": "비트코인", "english_name": "Bitcoin", "market_warning": "NONE"},
            {"market": "KRW-ETH", "korean_name": "이더리움", "english_name": "Ethereum", "market_warning": "CAUTION"},
            {"market": "BTC-ETH", "korean_name": "이더리움", "english_name": "Ethereum", "market_warning": "NONE"},
        ]
        with patch.object(client, "_get", return_value=mock_data):
            result = client.get_markets("KRW")
            assert len(result) == 2
            assert all(m["market"].startswith("KRW-") for m in result)

    def test_includes_market_warning(self, client):
        mock_data = [
            {"market": "KRW-BTC", "korean_name": "비트코인", "english_name": "Bitcoin", "market_warning": "CAUTION"},
        ]
        with patch.object(client, "_get", return_value=mock_data):
            result = client.get_markets("KRW")
            assert result[0]["market_warning"] == "CAUTION"


class TestGetTickers:
    def test_returns_ticker_list(self, client):
        mock_data = [
            {
                "market": "KRW-BTC",
                "trade_price": 50000000,
                "signed_change_rate": 0.02,
                "acc_trade_volume_24h": 1000,
                "high_price": 51000000,
                "low_price": 49000000,
            },
            {
                "market": "KRW-ETH",
                "trade_price": 3000000,
                "signed_change_rate": -0.01,
                "acc_trade_volume_24h": 5000,
                "high_price": 3100000,
                "low_price": 2900000,
            },
        ]
        with patch.object(client, "_get", return_value=mock_data):
            result = client.get_tickers(["KRW-BTC", "KRW-ETH"])
            assert len(result) == 2
            assert result[0].symbol == "KRW-BTC"
            assert result[0].price == 50000000
            assert result[1].symbol == "KRW-ETH"

    def test_empty_symbols(self, client):
        result = client.get_tickers([])
        assert result == []


class TestGetTopVolumeSymbols:
    def test_returns_sorted_by_volume(self, client):
        markets_data = [
            {"market": "KRW-BTC", "korean_name": "비트코인", "english_name": "Bitcoin", "market_warning": "NONE"},
            {"market": "KRW-ETH", "korean_name": "이더리움", "english_name": "Ethereum", "market_warning": "NONE"},
            {"market": "KRW-XRP", "korean_name": "리플", "english_name": "Ripple", "market_warning": "NONE"},
        ]
        ticker_data = [
            {"market": "KRW-BTC", "trade_price": 50000000, "signed_change_rate": 0.01,
             "acc_trade_volume_24h": 500, "high_price": 51000000, "low_price": 49000000},
            {"market": "KRW-ETH", "trade_price": 3000000, "signed_change_rate": 0.01,
             "acc_trade_volume_24h": 10000, "high_price": 3100000, "low_price": 2900000},
            {"market": "KRW-XRP", "trade_price": 1000, "signed_change_rate": 0.01,
             "acc_trade_volume_24h": 5000000, "high_price": 1100, "low_price": 900},
        ]

        def mock_get(path, params=None, auth=False):
            if "market/all" in path:
                return markets_data
            return ticker_data

        with patch.object(client, "_get", side_effect=mock_get):
            # BTC: 50M * 500 = 25B, ETH: 3M * 10K = 30B, XRP: 1K * 5M = 5B
            result = client.get_top_volume_symbols(min_volume_krw=0)
            assert result[0] == "KRW-ETH"  # 최대 거래대금
            assert result[1] == "KRW-BTC"

    def test_excludes_warning_coins(self, client):
        markets_data = [
            {"market": "KRW-BTC", "korean_name": "비트코인", "english_name": "Bitcoin", "market_warning": "NONE"},
            {"market": "KRW-SCAM", "korean_name": "스캠코인", "english_name": "Scam", "market_warning": "CAUTION"},
        ]
        ticker_data = [
            {"market": "KRW-BTC", "trade_price": 50000000, "signed_change_rate": 0.01,
             "acc_trade_volume_24h": 500, "high_price": 51000000, "low_price": 49000000},
        ]

        def mock_get(path, params=None, auth=False):
            if "market/all" in path:
                return markets_data
            return ticker_data

        with patch.object(client, "_get", side_effect=mock_get):
            result = client.get_top_volume_symbols(min_volume_krw=0)
            assert "KRW-SCAM" not in result
            assert "KRW-BTC" in result

    def test_min_volume_filter(self, client):
        markets_data = [
            {"market": "KRW-BTC", "korean_name": "비트코인", "english_name": "Bitcoin", "market_warning": "NONE"},
            {"market": "KRW-SMALL", "korean_name": "소형코인", "english_name": "Small", "market_warning": "NONE"},
        ]
        ticker_data = [
            {"market": "KRW-BTC", "trade_price": 50000000, "signed_change_rate": 0.01,
             "acc_trade_volume_24h": 500, "high_price": 51000000, "low_price": 49000000},
            {"market": "KRW-SMALL", "trade_price": 100, "signed_change_rate": 0.01,
             "acc_trade_volume_24h": 100, "high_price": 110, "low_price": 90},
        ]

        def mock_get(path, params=None, auth=False):
            if "market/all" in path:
                return markets_data
            return ticker_data

        with patch.object(client, "_get", side_effect=mock_get):
            # BTC: 25B, SMALL: 10K → 최소 100억으로 필터
            result = client.get_top_volume_symbols(min_volume_krw=10_000_000_000)
            assert "KRW-BTC" in result
            assert "KRW-SMALL" not in result

    def test_limit_parameter(self, client):
        markets_data = [
            {"market": f"KRW-COIN{i}", "korean_name": f"코인{i}", "english_name": f"Coin{i}", "market_warning": "NONE"}
            for i in range(5)
        ]
        ticker_data = [
            {"market": f"KRW-COIN{i}", "trade_price": 1000000, "signed_change_rate": 0.01,
             "acc_trade_volume_24h": 100000 * (5 - i), "high_price": 1100000, "low_price": 900000}
            for i in range(5)
        ]

        def mock_get(path, params=None, auth=False):
            if "market/all" in path:
                return markets_data
            return ticker_data

        with patch.object(client, "_get", side_effect=mock_get):
            result = client.get_top_volume_symbols(limit=2, min_volume_krw=0)
            assert len(result) == 2
