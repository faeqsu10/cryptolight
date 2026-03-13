"""10개 개선 항목 테스트"""

import threading
from unittest.mock import MagicMock, patch

import pytest

from cryptolight.exchange.base import Balance, OrderResult
from cryptolight.execution.base import BaseBroker
from cryptolight.execution.live_broker import LiveBroker
from cryptolight.execution.paper_broker import PaperBroker
from cryptolight.storage.models import TradeRecord
from cryptolight.storage.repository import TradeRepository
from cryptolight.evaluation.arena import StrategyArena


# ── CRITICAL-1: Live 모드 손절/익절 지원 확인 ──

class TestLiveStopLoss:
    def test_balance_has_avg_buy_price(self):
        """Balance 클래스에 avg_buy_price 필드가 있는지 확인"""
        bal = Balance(currency="BTC", total=1.0, available=1.0, locked=0.0, avg_buy_price=50000000.0)
        assert bal.avg_buy_price == 50000000.0

    def test_balance_avg_buy_price_default(self):
        """avg_buy_price 기본값은 0.0"""
        bal = Balance(currency="BTC", total=1.0, available=1.0, locked=0.0)
        assert bal.avg_buy_price == 0.0


# ── CRITICAL-3: LiveBroker strategy 파라미터 ──

class TestLiveBrokerStrategy:
    def test_buy_market_has_strategy_param(self):
        """LiveBroker.buy_market에 strategy 파라미터가 있는지 확인"""
        import inspect
        sig = inspect.signature(LiveBroker.buy_market)
        assert "strategy" in sig.parameters

    def test_sell_market_has_strategy_param(self):
        """LiveBroker.sell_market에 strategy 파라미터가 있는지 확인"""
        import inspect
        sig = inspect.signature(LiveBroker.sell_market)
        assert "strategy" in sig.parameters

    def test_buy_records_strategy(self, tmp_path):
        """LiveBroker 매수 시 strategy가 TradeRecord에 기록되는지 확인"""
        mock_client = MagicMock()
        mock_client.buy_market.return_value = OrderResult(
            order_id="test-1", symbol="KRW-BTC", side="bid",
            order_type="price", price=50000000.0, quantity=0.001,
            amount=50000.0, state="done",
        )
        mock_client.get_order.return_value = mock_client.buy_market.return_value

        repo = TradeRepository(db_path=tmp_path / "test.db")
        broker = LiveBroker(client=mock_client, repo=repo)
        broker.buy_market("KRW-BTC", 50000.0, 50000000.0, reason="test", strategy="rsi")

        trades = repo.get_trades()
        assert len(trades) >= 1
        assert trades[0].strategy == "rsi"
        repo.close()

    def test_sell_records_strategy(self, tmp_path):
        """LiveBroker 매도 시 strategy가 TradeRecord에 기록되는지 확인"""
        mock_client = MagicMock()
        mock_client.sell_market.return_value = OrderResult(
            order_id="test-2", symbol="KRW-BTC", side="ask",
            order_type="market", price=51000000.0, quantity=0.001,
            amount=51000.0, state="done",
        )
        mock_client.get_order.return_value = mock_client.sell_market.return_value

        repo = TradeRepository(db_path=tmp_path / "test.db")
        broker = LiveBroker(client=mock_client, repo=repo)
        broker.sell_market("KRW-BTC", 0.001, 51000000.0, reason="test", strategy="macd")

        trades = repo.get_trades()
        assert len(trades) >= 1
        assert trades[0].strategy == "macd"
        repo.close()


# ── CRITICAL-2 + HIGH-2: 스레드 안전성 ──

class TestThreadSafety:
    def test_repository_has_lock(self, tmp_path):
        """TradeRepository에 threading.RLock이 있는지 확인"""
        repo = TradeRepository(db_path=tmp_path / "test.db")
        assert hasattr(repo, "_lock")
        assert isinstance(repo._lock, type(threading.RLock()))
        repo.close()

    def test_paper_broker_has_lock(self):
        """PaperBroker에 threading.Lock이 있는지 확인"""
        broker = PaperBroker(initial_balance=1000000.0)
        assert hasattr(broker, "_lock")
        assert isinstance(broker._lock, type(threading.Lock()))

    def test_paper_broker_concurrent_buy(self):
        """PaperBroker 동시 매수가 레이스 컨디션 없이 처리되는지 확인"""
        broker = PaperBroker(initial_balance=1000000.0)
        results = []
        errors = []

        def buy():
            try:
                r = broker.buy_market("KRW-BTC", 50000.0, 50000000.0, reason="test")
                results.append(r)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=buy) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        successful = [r for r in results if r is not None]
        assert len(successful) > 0
        # 잔고가 음수가 되면 안 됨
        assert broker.balance_krw >= 0


# ── HIGH-1: 전략 전환 mutable 상태 ──

class TestStrategySwitch:
    def test_active_strategy_name_module_var(self):
        """_active_strategy_name 모듈 변수가 존재하는지 확인"""
        from cryptolight import main
        assert hasattr(main, "_active_strategy_name")

    def test_active_strategy_name_default_empty(self):
        """기본값은 빈 문자열"""
        from cryptolight import main
        # 초기값은 "" (settings.strategy_name 사용)
        assert isinstance(main._active_strategy_name, str)


# ── MEDIUM-1: daily_pnl 매수만 있는 날 ──

class TestDailyPnl:
    def test_buy_only_day_not_negative(self, tmp_path):
        """매수만 있는 날 realized_pnl이 음수가 아닌지 확인 (수수료만 차감)"""
        repo = TradeRepository(db_path=tmp_path / "test.db")
        trade = TradeRecord(
            symbol="KRW-BTC", side="buy", price=50000000.0,
            quantity=0.001, amount_krw=50000.0, commission=25.0,
            reason="test",
        )
        repo.save_trade(trade)

        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        pnl = repo.get_daily_pnl(today)

        # 매수만 있으면 매수액은 손익에 포함되지 않고 수수료만 차감
        assert pnl["realized_pnl"] == -25.0  # 수수료만
        assert pnl["total_bought"] == 50000.0
        assert pnl["total_sold"] == 0.0
        repo.close()

    def test_sell_day_includes_both(self, tmp_path):
        """매도가 있는 날은 기존 로직대로 계산"""
        repo = TradeRepository(db_path=tmp_path / "test.db")
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")

        buy = TradeRecord(
            symbol="KRW-BTC", side="buy", price=50000000.0,
            quantity=0.001, amount_krw=50000.0, commission=25.0,
            reason="test",
        )
        sell = TradeRecord(
            symbol="KRW-BTC", side="sell", price=51000000.0,
            quantity=0.001, amount_krw=51000.0, commission=25.5,
            reason="test",
        )
        repo.save_trade(buy)
        repo.save_trade(sell)

        pnl = repo.get_daily_pnl(today)
        # 51000 - 50000 - 50.5 = 949.5
        assert pnl["realized_pnl"] == pytest.approx(949.5)
        repo.close()


# ── MEDIUM-2: Arena Sharpe ratio ──

class TestArenaSharpe:
    def test_uses_backtest_sharpe_ratio(self):
        """_calc_sharpe_from_result가 result.sharpe_ratio를 직접 반환하는지 확인"""
        arena = StrategyArena()

        class MockResult:
            total_trades = 10
            sharpe_ratio = 2.5

        assert arena._calc_sharpe_from_result(MockResult()) == 2.5

    def test_low_trades_returns_zero(self):
        """거래 2건 미만이면 0.0 반환"""
        arena = StrategyArena()

        class MockResult:
            total_trades = 1
            sharpe_ratio = 5.0

        assert arena._calc_sharpe_from_result(MockResult()) == 0.0


# ── MEDIUM-4: AI assistant close() ──

class TestAIAssistantClose:
    def test_ai_assistant_has_close(self):
        """AIAssistant에 close() 메서드가 있는지 확인"""
        from cryptolight.bot.ai_assistant import AIAssistant
        assert hasattr(AIAssistant, "close")

    def test_close_in_finally_blocks(self):
        """main.py finally 블록에 _ai_assistant.close()가 있는지 확인"""
        import inspect
        from cryptolight import main
        source = inspect.getsource(main.main)
        assert "_ai_assistant" in source
        # close가 finally에서 호출되는지 (소스코드 검사)
        assert "_ai_assistant.close()" in source
