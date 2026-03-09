"""StrategyTracker 전략 성과 추적 테스트"""
import tempfile
from pathlib import Path

from cryptolight.storage.models import TradeRecord
from cryptolight.storage.repository import TradeRepository
from cryptolight.storage.strategy_tracker import StrategyTracker


def _temp_repo():
    tmp = tempfile.mkdtemp()
    return TradeRepository(db_path=Path(tmp) / "test.db")


def test_empty_stats():
    repo = _temp_repo()
    tracker = StrategyTracker(repo)
    stats = tracker.get_strategy_stats()
    assert stats == []
    repo.close()


def test_strategy_stats():
    repo = _temp_repo()
    repo.save_trade(TradeRecord(
        symbol="KRW-BTC", side="buy", price=100000, quantity=0.001,
        amount_krw=100, commission=0.05, reason="test", strategy="rsi",
    ))
    repo.save_trade(TradeRecord(
        symbol="KRW-BTC", side="sell", price=110000, quantity=0.001,
        amount_krw=110, commission=0.055, reason="test", strategy="rsi",
    ))

    tracker = StrategyTracker(repo)
    stats = tracker.get_strategy_stats()
    assert len(stats) == 1
    assert stats[0]["strategy"] == "rsi"
    assert stats[0]["trade_count"] == 2
    repo.close()


def test_summary_text():
    repo = _temp_repo()
    repo.save_trade(TradeRecord(
        symbol="KRW-BTC", side="buy", price=100000, quantity=0.001,
        amount_krw=100, commission=0.05, reason="test", strategy="macd",
    ))
    tracker = StrategyTracker(repo)
    text = tracker.summary_text()
    assert "macd" in text
    repo.close()


def test_empty_summary():
    repo = _temp_repo()
    tracker = StrategyTracker(repo)
    text = tracker.summary_text()
    assert "데이터 없음" in text
    repo.close()


def test_win_rate_no_sells():
    repo = _temp_repo()
    repo.save_trade(TradeRecord(
        symbol="KRW-BTC", side="buy", price=100000, quantity=0.001,
        amount_krw=100, commission=0.05, reason="test", strategy="rsi",
    ))
    tracker = StrategyTracker(repo)
    wr = tracker.get_strategy_win_rate("rsi")
    assert wr["total_sells"] == 0
    assert wr["win_rate"] == 0.0
    repo.close()


def test_win_rate_winning_trade():
    repo = _temp_repo()
    repo.save_trade(TradeRecord(
        symbol="KRW-BTC", side="buy", price=100000, quantity=0.001,
        amount_krw=100, commission=0.05, reason="test", strategy="rsi",
    ))
    repo.save_trade(TradeRecord(
        symbol="KRW-BTC", side="sell", price=110000, quantity=0.001,
        amount_krw=110, commission=0.055, reason="test", strategy="rsi",
    ))
    tracker = StrategyTracker(repo)
    wr = tracker.get_strategy_win_rate("rsi")
    assert wr["total_sells"] == 1
    assert wr["wins"] == 1
    assert wr["win_rate"] == 100.0
    repo.close()


def test_win_rate_losing_trade():
    repo = _temp_repo()
    repo.save_trade(TradeRecord(
        symbol="KRW-BTC", side="buy", price=110000, quantity=0.001,
        amount_krw=110, commission=0.055, reason="test", strategy="macd",
    ))
    repo.save_trade(TradeRecord(
        symbol="KRW-BTC", side="sell", price=100000, quantity=0.001,
        amount_krw=100, commission=0.05, reason="test", strategy="macd",
    ))
    tracker = StrategyTracker(repo)
    wr = tracker.get_strategy_win_rate("macd")
    assert wr["total_sells"] == 1
    assert wr["wins"] == 0
    assert wr["win_rate"] == 0.0
    repo.close()


def test_win_rate_strategy_isolation():
    repo = _temp_repo()
    # rsi: 수익 거래
    repo.save_trade(TradeRecord(
        symbol="KRW-BTC", side="buy", price=100000, quantity=0.001,
        amount_krw=100, commission=0.05, reason="test", strategy="rsi",
    ))
    repo.save_trade(TradeRecord(
        symbol="KRW-BTC", side="sell", price=120000, quantity=0.001,
        amount_krw=120, commission=0.06, reason="test", strategy="rsi",
    ))
    # macd: 손실 거래
    repo.save_trade(TradeRecord(
        symbol="KRW-BTC", side="buy", price=120000, quantity=0.001,
        amount_krw=120, commission=0.06, reason="test", strategy="macd",
    ))
    repo.save_trade(TradeRecord(
        symbol="KRW-BTC", side="sell", price=100000, quantity=0.001,
        amount_krw=100, commission=0.05, reason="test", strategy="macd",
    ))
    tracker = StrategyTracker(repo)
    rsi_wr = tracker.get_strategy_win_rate("rsi")
    macd_wr = tracker.get_strategy_win_rate("macd")
    assert rsi_wr["win_rate"] == 100.0
    assert macd_wr["win_rate"] == 0.0
    repo.close()
