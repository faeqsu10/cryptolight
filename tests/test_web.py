"""웹 대시보드 API 테스트"""

import pytest
from fastapi.testclient import TestClient

from cryptolight.web.app import app, configure


@pytest.fixture
def client():
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

    def test_security_headers(self, client):
        resp = client.get("/")
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert "Content-Security-Policy" in resp.headers


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

    def test_limit_validation(self, client):
        resp = client.get("/api/trades?limit=0")
        assert resp.status_code == 422

        resp = client.get("/api/trades?limit=999")
        assert resp.status_code == 422


class TestStatusAPI:
    def test_no_settings_returns_defaults(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy"] == "N/A"
        assert data["trade_mode"] == "N/A"

    def test_with_health_monitor(self):
        from cryptolight.health import HealthMonitor

        hm = HealthMonitor()
        hm.record_success()
        hm.record_success()
        configure(market_snapshots={}, broker=None, repo=None, health=hm, settings=None)
        c = TestClient(app)
        resp = c.get("/api/status")
        data = resp.json()
        assert data["health"]["total_cycles"] == 2
        assert data["health"]["consecutive_errors"] == 0
        assert data["health"]["healthy"] is True


class TestOpenAPIDisabled:
    def test_no_openapi_schema(self, client):
        resp = client.get("/openapi.json")
        assert resp.status_code == 404
