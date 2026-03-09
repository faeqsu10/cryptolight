"""백테스트 엔진 테스트"""
from cryptolight.backtest.engine import BacktestEngine
from cryptolight.exchange.base import Candle
from cryptolight.strategy.base import BaseStrategy, Signal


class AlwaysBuyStrategy(BaseStrategy):
    """테스트용: 항상 매수."""
    def analyze(self, candles):
        return Signal(action="buy", symbol="TEST", reason="test", confidence=1.0)
    def required_candle_count(self):
        return 1


class AlternateBuySellStrategy(BaseStrategy):
    """테스트용: 매수/매도 반복."""
    def __init__(self):
        self._count = 0
    def analyze(self, candles):
        self._count += 1
        action = "buy" if self._count % 2 == 1 else "sell"
        return Signal(action=action, symbol="TEST", reason="test", confidence=1.0)
    def required_candle_count(self):
        return 1


def _make_candles(prices: list[float]) -> list[Candle]:
    return [
        Candle(timestamp=f"2024-01-{i+1:02d}", open=p, high=p+100, low=p-100, close=p, volume=100)
        for i, p in enumerate(prices)
    ]


def test_backtest_no_trades():
    """매매 없으면 수익률 0."""
    candles = _make_candles([50000] * 20)
    engine = BacktestEngine(AlwaysBuyStrategy(), initial_balance=100_000, order_amount=100_000)
    result = engine.run(candles)
    # 첫 매수 후 잔고가 소진되어 추가 매수 불가, 매도 없음
    assert result.sell_trades == 0


def test_backtest_buy_sell_cycle():
    """매수/매도 사이클 테스트."""
    prices = [50000, 50000, 51000, 51000, 52000, 52000, 53000, 53000, 54000, 54000]
    candles = _make_candles(prices)
    engine = BacktestEngine(
        AlternateBuySellStrategy(), initial_balance=1_000_000, order_amount=50_000,
    )
    result = engine.run(candles)
    assert result.buy_trades > 0
    assert result.sell_trades > 0
    assert result.total_trades == result.buy_trades + result.sell_trades


def test_backtest_buy_hold_benchmark():
    """Buy&Hold 벤치마크가 계산된다."""
    prices = [50000 + i * 1000 for i in range(30)]
    candles = _make_candles(prices)
    engine = BacktestEngine(AlwaysBuyStrategy(), initial_balance=1_000_000, order_amount=50_000)
    result = engine.run(candles)
    assert result.buy_hold_return_pct != 0.0
    assert result.buy_hold_final_equity > 0


def test_backtest_slippage_impact():
    """슬리피지가 수익률에 영향을 준다."""
    prices = [50000, 50000, 51000, 50000, 51000, 50000, 51000, 50000, 51000, 50000]
    candles = _make_candles(prices)
    strat1 = AlternateBuySellStrategy()
    strat2 = AlternateBuySellStrategy()

    r_no_slip = BacktestEngine(strat1, order_amount=50_000, slippage_pct=0, spread_pct=0).run(candles)
    r_with_slip = BacktestEngine(strat2, order_amount=50_000, slippage_pct=0.5, spread_pct=0.3).run(candles)

    # 슬리피지 있으면 수익률이 같거나 낮아야 함
    assert r_with_slip.final_equity <= r_no_slip.final_equity


def test_backtest_summary_text():
    """summary_text에 Buy&Hold, Alpha가 포함된다."""
    candles = _make_candles([50000 + i * 100 for i in range(30)])
    engine = BacktestEngine(AlwaysBuyStrategy(), order_amount=50_000)
    result = engine.run(candles)
    text = engine.summary_text(result)
    assert "Buy&Hold" in text
    assert "Alpha" in text


def test_backtest_mdd():
    """하락 구간에서 MDD가 음수."""
    prices = [50000, 55000, 45000, 40000, 50000]  # 하락 후 회복
    candles = _make_candles(prices)
    engine = BacktestEngine(AlwaysBuyStrategy(), initial_balance=1_000_000, order_amount=50_000)
    result = engine.run(candles)
    assert result.max_drawdown_pct <= 0
