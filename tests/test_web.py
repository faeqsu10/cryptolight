"""웹 대시보드 API 테스트"""

import pytest

from cryptolight.web.app import app, configure


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    configure(
        market_snapshots={
            "KRW-BTC": {
                "price": 50_000_000,
                "change": 2.5,
                "rsi": 45.0,
                "action": "hold",
                "regime": "trending",
                "adx": 30.0,
                "weight": 1.0,
            }
        },
        broker=None,
        repo=None,
        health=None,
        settings=None,
    )
    return TestClient(app)


class TestDashboardPage:
    def test_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "cryptolight" in resp.text


class TestMarketAPI:
    def test_returns_market_data(self, client):
        resp = client.get("/api/market")
        assert resp.status_code == 200
        data = resp.json()
        assert "KRW-BTC" in data
        assert data["KRW-BTC"]["price"] == 50_000_000
        assert data["KRW-BTC"]["rsi"] == 45.0
        assert data["KRW-BTC"]["action"] == "hold"
        assert data["KRW-BTC"]["regime"] == "trending"

    def test_empty_market(self):
        from fastapi.testclient import TestClient

        configure(market_snapshots={}, broker=None, repo=None, health=None, settings=None)
        c = TestClient(app)
        resp = c.get("/api/market")
        assert resp.status_code == 200
        assert resp.json() == {}


class TestPortfolioAPI:
    def test_no_broker_returns_zeros(self, client):
        resp = client.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cash"] == 0
        assert data["equity"] == 0
        assert data["positions"] == []


class TestTradesAPI:
    def test_no_repo_returns_empty(self, client):
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        assert resp.json() == []


class TestStatusAPI:
    def test_no_settings_returns_defaults(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy"] == "N/A"
        assert data["trade_mode"] == "N/A"
