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
                "updated_at": "2026-03-15T16:56:13",
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
        assert data["KRW-BTC"]["updated_at"] == "2026-03-15T16:56:13"

    def test_empty_market(self):
        configure(market_snapshots={}, broker=None, repo=None, health=None, settings=None)
        c = TestClient(app)
        resp = c.get("/api/market")
        assert resp.status_code == 200
        assert resp.json() == {}

    def test_market_snapshot_getter_overrides_static_data(self):
        configure(
            market_snapshots={},
            market_snapshot_getter=lambda: {
                "KRW-NOM": {
                    "price": 7,
                    "change": -3.2,
                    "rsi": 37.4,
                    "action": "buy",
                    "regime": "sideways",
                    "adx": 19.8,
                    "confidence": 0.6,
                    "indicators": {"buy_score": 45},
                    "updated_at": "2026-03-15T16:56:13",
                }
            },
            broker=None,
            repo=None,
            health=None,
            settings=None,
        )
        c = TestClient(app)
        resp = c.get("/api/market")
        data = resp.json()
        assert "KRW-NOM" in data
        assert data["KRW-NOM"]["updated_at"] == "2026-03-15T16:56:13"


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
        assert data["health"]["last_strategy_success"] is True

    def test_runtime_state_getter_overrides_static_status(self):
        from unittest.mock import MagicMock

        settings = MagicMock()
        settings.strategy_name = "score"
        settings.trade_mode = "paper"
        settings.symbol_list = ["KRW-BTC"]
        settings.schedule_interval_minutes = 60
        settings.web_username = ""
        settings.web_password = ""

        configure(
            market_snapshots={},
            broker=None,
            repo=None,
            health=None,
            settings=settings,
            runtime_state_getter=lambda: {
                "strategy_name": "ensemble",
                "trade_mode": "paper",
                "symbol_list": ["KRW-NOM", "KRW-ETH"],
                "schedule_interval_minutes": 15,
            },
        )
        c = TestClient(app)
        resp = c.get("/api/status")
        data = resp.json()

        assert data["strategy"] == "ensemble"
        assert data["symbols"] == ["KRW-NOM", "KRW-ETH"]
        assert data["interval_minutes"] == 15

    def test_uses_runtime_market_symbols_when_available(self):
        from unittest.mock import MagicMock

        settings = MagicMock()
        settings.strategy_name = "score"
        settings.trade_mode = "paper"
        settings.symbol_list = ["KRW-BTC", "KRW-ETH"]
        settings.schedule_interval_minutes = 60
        settings.web_username = ""
        settings.web_password = ""

        configure(
            market_snapshots={
                "KRW-NOM": {"price": 7.0, "updated_at": "2026-03-15T16:56:13"},
                "KRW-DKA": {"price": 8.1, "updated_at": "2026-03-15T16:56:17"},
            },
            broker=None,
            repo=None,
            health=None,
            settings=settings,
        )
        c = TestClient(app)
        resp = c.get("/api/status")
        data = resp.json()
        assert data["symbols"] == ["KRW-NOM", "KRW-DKA"]
        assert data["market_updated_at"] == "2026-03-15T16:56:17"


class TestOpenAPIDisabled:
    def test_no_openapi_schema(self, client):
        resp = client.get("/openapi.json")
        assert resp.status_code == 404


class TestHTTPBasicAuth:
    @pytest.fixture
    def auth_client(self):
        """인증이 설정된 웹 클라이언트."""
        from unittest.mock import MagicMock

        settings = MagicMock()
        settings.strategy_name = "score"
        settings.trade_mode = "paper"
        settings.symbol_list = ["KRW-BTC"]
        settings.schedule_interval_minutes = 5
        settings.web_username = "admin"
        settings.web_password = "secret"
        configure(
            market_snapshots={},
            broker=None,
            repo=None,
            health=None,
            settings=settings,
        )
        return TestClient(app, raise_server_exceptions=True)

    def test_no_auth_required_when_not_configured(self, client):
        """인증 미설정 시 자유롭게 접근 가능."""
        assert client.get("/").status_code == 200
        assert client.get("/api/market").status_code == 200
        assert client.get("/api/portfolio").status_code == 200
        assert client.get("/api/trades").status_code == 200
        assert client.get("/api/status").status_code == 200

    def test_401_when_no_credentials(self, auth_client):
        """인증 설정 후 자격증명 없이 접근 시 401."""
        resp = auth_client.get("/api/status", auth=None)
        assert resp.status_code == 401
        assert resp.headers.get("WWW-Authenticate") == "Basic"

    def test_401_wrong_credentials(self, auth_client):
        """잘못된 자격증명으로 접근 시 401."""
        resp = auth_client.get("/api/status", auth=("admin", "wrong"))
        assert resp.status_code == 401

    def test_200_correct_credentials(self, auth_client):
        """올바른 자격증명으로 접근 시 200."""
        resp = auth_client.get("/api/status", auth=("admin", "secret"))
        assert resp.status_code == 200

    def test_all_endpoints_protected(self, auth_client):
        """모든 엔드포인트가 인증으로 보호됨."""
        for path in ["/", "/api/market", "/api/portfolio", "/api/trades", "/api/status"]:
            resp = auth_client.get(path, auth=None)
            assert resp.status_code == 401, f"{path} should require auth"
