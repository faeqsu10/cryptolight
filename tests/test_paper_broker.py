"""PaperBroker 테스트"""
from cryptolight.execution.paper_broker import PaperBroker


def test_buy_market():
    broker = PaperBroker(initial_balance=1_000_000)
    order = broker.buy_market("KRW-BTC", 50_000, 100_000_000)
    assert order is not None
    assert order.side == "bid"
    assert broker.balance_krw < 1_000_000
    assert "KRW-BTC" in broker.positions


def test_buy_insufficient_balance():
    broker = PaperBroker(initial_balance=10_000)
    order = broker.buy_market("KRW-BTC", 50_000, 100_000_000)
    assert order is None


def test_sell_market():
    broker = PaperBroker(initial_balance=1_000_000)
    broker.buy_market("KRW-BTC", 50_000, 100_000_000)
    pos = broker.positions["KRW-BTC"]
    order = broker.sell_market("KRW-BTC", pos.quantity, 101_000_000)
    assert order is not None
    assert order.side == "ask"


def test_sell_no_position():
    broker = PaperBroker(initial_balance=1_000_000)
    order = broker.sell_market("KRW-BTC", 0.001, 100_000_000)
    assert order is None


def test_get_equity():
    broker = PaperBroker(initial_balance=1_000_000)
    broker.buy_market("KRW-BTC", 50_000, 100_000_000)
    equity = broker.get_equity({"KRW-BTC": 100_000_000})
    # 수수료만큼 줄어들지만 큰 차이 없어야
    assert 999_000 < equity < 1_001_000


def test_summary_text():
    broker = PaperBroker(initial_balance=1_000_000)
    broker.buy_market("KRW-BTC", 50_000, 100_000_000)
    text = broker.summary_text({"KRW-BTC": 100_000_000})
    assert "현금" in text
    assert "총 자산" in text
