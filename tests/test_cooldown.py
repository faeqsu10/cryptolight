"""TradeCooldown 이상 거래 감지 테스트"""
from cryptolight.risk.cooldown import TradeCooldown


def test_first_trade_allowed():
    cd = TradeCooldown(cooldown_seconds=60)
    ok, reason = cd.can_trade("KRW-BTC")
    assert ok is True
    assert reason == ""


def test_cooldown_blocks():
    cd = TradeCooldown(cooldown_seconds=60)
    cd.record_trade("KRW-BTC")
    ok, reason = cd.can_trade("KRW-BTC")
    assert ok is False
    assert "쿨다운" in reason


def test_different_symbol_not_blocked():
    cd = TradeCooldown(cooldown_seconds=60)
    cd.record_trade("KRW-BTC")
    ok, reason = cd.can_trade("KRW-ETH")
    assert ok is True


def test_max_orders_per_hour():
    cd = TradeCooldown(cooldown_seconds=0, max_orders_per_hour=3)
    for i in range(3):
        cd.record_trade(f"SYM-{i}")
    ok, reason = cd.can_trade("SYM-NEW")
    assert ok is False
    assert "한도" in reason
