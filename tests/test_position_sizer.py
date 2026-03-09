"""PositionSizer 포지션 사이징 테스트"""
from cryptolight.risk.position_sizer import PositionSizer


def test_fixed_mode():
    sizer = PositionSizer(method="fixed", fixed_amount=50_000)
    assert sizer.calculate(1_000_000) == 50_000


def test_fixed_with_confidence():
    sizer = PositionSizer(method="fixed", fixed_amount=50_000)
    amount = sizer.calculate(1_000_000, confidence=0.5)
    assert amount == 25_000


def test_percent_mode():
    sizer = PositionSizer(method="percent", risk_pct=2.0)
    amount = sizer.calculate(1_000_000)
    assert amount == 20_000  # 1M * 2%


def test_percent_with_confidence():
    sizer = PositionSizer(method="percent", risk_pct=5.0)
    amount = sizer.calculate(1_000_000, confidence=0.6)
    assert amount == 30_000  # 1M * 5% * 0.6


def test_kelly_mode():
    sizer = PositionSizer(
        method="kelly", kelly_win_rate=0.6,
        kelly_avg_win=2.0, kelly_avg_loss=1.0, kelly_fraction=0.25,
    )
    amount = sizer.calculate(1_000_000)
    assert 5_000 <= amount <= 500_000


def test_max_amount_cap():
    sizer = PositionSizer(method="percent", risk_pct=100, max_amount=100_000)
    amount = sizer.calculate(10_000_000)
    assert amount == 100_000


def test_min_amount():
    sizer = PositionSizer(method="fixed", fixed_amount=1_000)
    amount = sizer.calculate(100_000, confidence=0.01)
    assert amount == 5_000  # 최소 5천원


def test_update_kelly_stats():
    sizer = PositionSizer(method="kelly")
    sizer.update_kelly_stats(0.55, 1.5, 1.0)
    assert sizer.kelly_win_rate == 0.55
    assert sizer.kelly_avg_win == 1.5
