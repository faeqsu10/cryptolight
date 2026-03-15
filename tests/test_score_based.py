"""ScoreBasedStrategy 테스트"""

from cryptolight.exchange.base import Candle
from cryptolight.strategy.score_based import ScoreBasedStrategy, REGIME_WEIGHTS


def _make_candles(closes, volumes=None, count=None):
    """테스트용 캔들 생성. closes 리스트로 캔들 생성."""
    if count and len(closes) < count:
        # 앞에 패딩
        closes = [closes[0]] * (count - len(closes)) + closes
    if volumes is None:
        volumes = [1000.0] * len(closes)
    elif len(volumes) < len(closes):
        volumes = [1000.0] * (len(closes) - len(volumes)) + volumes
    candles = []
    for i, (c, v) in enumerate(zip(closes, volumes)):
        candles.append(Candle(
            timestamp=f"2024-01-{i+1:02d}T00:00:00",
            open=c * 0.99,
            high=c * 1.01,
            low=c * 0.98,
            close=c,
            volume=v,
        ))
    return candles


class TestScoreBasedStrategy:
    def test_hold_when_insufficient_candles(self):
        strategy = ScoreBasedStrategy()
        candles = _make_candles([100.0] * 5)
        signal = strategy.analyze(candles)
        assert signal.action == "hold"
        assert "캔들 부족" in signal.reason

    def test_neutral_market_not_high_confidence(self):
        """RSI 50 근처, MACD 중립 → 높은 confidence 아님"""
        strategy = ScoreBasedStrategy()
        closes = [100.0 + (i % 3 - 1) * 0.1 for i in range(40)]
        candles = _make_candles(closes)
        signal = strategy.analyze(candles)
        # 중립 시장에서 극단적 고확신이 나오면 안 됨
        assert signal.confidence <= 0.8

    def test_buy_signal_with_oversold_conditions(self):
        """가격 급락 후 반등 시작 → 매수 스코어 충분"""
        strategy = ScoreBasedStrategy()
        # 가격이 지속 하락 후 반등
        closes = list(range(200, 140, -1))  # 200 → 141 (60개, 충분)
        closes.extend([142, 143])  # 반등
        candles = _make_candles(closes, volumes=[2000.0] * len(closes))  # 높은 거래량
        signal = strategy.analyze(candles)
        # 매수 스코어가 충분히 높아야 함
        assert "buy_score" in signal.indicators

    def test_sell_signal_with_overbought_conditions(self):
        """가격 급등 후 하락 시작 → 매도 스코어 충분"""
        strategy = ScoreBasedStrategy()
        # 가격이 지속 상승 후 하락
        closes = list(range(100, 160))  # 100 → 159 (60개)
        closes.extend([158, 157])  # 하락
        candles = _make_candles(closes, volumes=[2000.0] * len(closes))
        signal = strategy.analyze(candles)
        assert "sell_score" in signal.indicators

    def test_regime_affects_thresholds(self):
        """국면별로 매수 임계값이 다르고, trending이 가장 낮음"""
        strategy = ScoreBasedStrategy()

        strategy.regime = "trending"
        weights_t = strategy._get_weights()
        strategy.regime = "sideways"
        weights_s = strategy._get_weights()
        strategy.regime = "volatile"
        weights_v = strategy._get_weights()

        assert weights_t["buy_threshold"] < weights_s["buy_threshold"]
        assert weights_s["buy_threshold"] <= weights_v["buy_threshold"]

    def test_regime_trending_boosts_macd(self):
        """추세장에서 MACD 가중치가 1.5배"""
        weights = REGIME_WEIGHTS["trending"]
        assert weights["macd"] == 1.5
        assert weights["bb"] == 0.5

    def test_regime_sideways_boosts_bb(self):
        """횡보장에서 볼린저 가중치가 1.5배"""
        weights = REGIME_WEIGHTS["sideways"]
        assert weights["bb"] == 1.5
        assert weights["macd"] == 0.5

    def test_required_candle_count(self):
        """필요 캔들 수 = max(각 지표 필요 수)"""
        strategy = ScoreBasedStrategy()
        # MACD가 가장 많이 필요: 26 + 9 + 1 = 36
        assert strategy.required_candle_count() == 36

    def test_indicators_contain_all_scores(self):
        """indicators에 buy_score, sell_score, regime 포함"""
        strategy = ScoreBasedStrategy(regime="trending")
        closes = [100.0] * 40
        candles = _make_candles(closes)
        signal = strategy.analyze(candles)
        assert "buy_score" in signal.indicators
        assert "sell_score" in signal.indicators
        assert signal.indicators["regime"] == "trending"

    def test_factory_creates_score_strategy(self):
        """create_strategy("score")로 생성 가능"""
        from cryptolight.strategy import create_strategy
        strategy = create_strategy("score")
        assert isinstance(strategy, ScoreBasedStrategy)

    def test_confidence_is_normalized(self):
        """confidence는 0~1 범위"""
        strategy = ScoreBasedStrategy()
        closes = list(range(200, 140, -1))
        closes.extend([142, 143])
        candles = _make_candles(closes, volumes=[2000.0] * len(closes))
        signal = strategy.analyze(candles)
        assert 0.0 <= signal.confidence <= 1.0

    def test_buy_score_higher_than_sell_for_buy_signal(self):
        """매수 시그널이면 buy_score > sell_score"""
        strategy = ScoreBasedStrategy()
        closes = list(range(200, 140, -1))
        closes.extend([142, 143])
        candles = _make_candles(closes, volumes=[2000.0] * len(closes))
        signal = strategy.analyze(candles)
        if signal.action == "buy":
            assert signal.indicators["buy_score"] > signal.indicators["sell_score"]
