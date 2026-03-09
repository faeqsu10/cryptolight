"""RiskGuard 리스크 관리 테스트"""
from cryptolight.risk.risk_guard import RiskGuard


def test_check_buy_pass():
    rg = RiskGuard(max_order_amount_krw=50_000, daily_loss_limit_krw=100_000)
    result = rg.check_buy("KRW-BTC", 50_000, balance_krw=100_000, active_positions=0, already_holding=False)
    assert result.allowed is True


def test_check_buy_over_limit():
    rg = RiskGuard(max_order_amount_krw=50_000, daily_loss_limit_krw=100_000)
    result = rg.check_buy("KRW-BTC", 60_000, balance_krw=100_000, active_positions=0, already_holding=False)
    assert result.allowed is False
    assert "한도" in result.reason


def test_check_buy_insufficient_balance():
    rg = RiskGuard(max_order_amount_krw=50_000, daily_loss_limit_krw=100_000)
    result = rg.check_buy("KRW-BTC", 50_000, balance_krw=10_000, active_positions=0, already_holding=False)
    assert result.allowed is False
    assert "잔고" in result.reason


def test_check_buy_max_positions():
    rg = RiskGuard(max_order_amount_krw=50_000, daily_loss_limit_krw=100_000, max_positions=3)
    result = rg.check_buy("KRW-BTC", 50_000, balance_krw=100_000, active_positions=3, already_holding=False)
    assert result.allowed is False
    assert "한도 초과" in result.reason


def test_check_buy_already_holding():
    """이미 보유 중이면 포지션 수 제한에 걸리지 않는다."""
    rg = RiskGuard(max_order_amount_krw=50_000, daily_loss_limit_krw=100_000, max_positions=3)
    result = rg.check_buy("KRW-BTC", 50_000, balance_krw=100_000, active_positions=3, already_holding=True)
    assert result.allowed is True


def test_stop_loss():
    rg = RiskGuard(max_order_amount_krw=50_000, daily_loss_limit_krw=100_000, stop_loss_pct=-5.0)
    result = rg.check_stop_loss_take_profit("BTC", avg_price=100_000, quantity=0.001, current_price=94_000)
    assert result == "stop_loss"


def test_take_profit():
    rg = RiskGuard(max_order_amount_krw=50_000, daily_loss_limit_krw=100_000, take_profit_pct=10.0)
    result = rg.check_stop_loss_take_profit("BTC", avg_price=100_000, quantity=0.001, current_price=111_000)
    assert result == "take_profit"


def test_no_trigger():
    rg = RiskGuard(max_order_amount_krw=50_000, daily_loss_limit_krw=100_000)
    result = rg.check_stop_loss_take_profit("BTC", avg_price=100_000, quantity=0.001, current_price=102_000)
    assert result is None


def test_trailing_stop():
    """트레일링 스톱: 고점 대비 하락 시 매도."""
    rg = RiskGuard(
        max_order_amount_krw=50_000, daily_loss_limit_krw=100_000,
        take_profit_pct=20.0, trailing_stop_pct=3.0,
    )
    # 가격 상승 → 고점 추적
    assert rg.check_stop_loss_take_profit("BTC", 100_000, 0.001, 110_000) is None
    assert rg.check_stop_loss_take_profit("BTC", 100_000, 0.001, 115_000) is None
    # 고점(115000) 대비 3% 하락 = 111,550 이하
    result = rg.check_stop_loss_take_profit("BTC", 100_000, 0.001, 111_000)
    assert result == "trailing_stop"


def test_trailing_stop_disabled():
    """trailing_stop_pct=0이면 트레일링 스톱 비활성화."""
    rg = RiskGuard(
        max_order_amount_krw=50_000, daily_loss_limit_krw=100_000,
        take_profit_pct=20.0, trailing_stop_pct=0.0,
    )
    assert rg.check_stop_loss_take_profit("BTC", 100_000, 0.001, 115_000) is None
    assert rg.check_stop_loss_take_profit("BTC", 100_000, 0.001, 111_000) is None


def test_zero_quantity():
    rg = RiskGuard(max_order_amount_krw=50_000, daily_loss_limit_krw=100_000)
    assert rg.check_stop_loss_take_profit("BTC", 100_000, 0, 50_000) is None
