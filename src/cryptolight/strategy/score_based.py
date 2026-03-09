"""멀티팩터 스코어 기반 전략 — 여러 지표가 동시에 같은 방향을 가리킬 때만 매매"""

import logging
import statistics

from cryptolight.exchange.base import Candle
from cryptolight.strategy.base import BaseStrategy, Signal
from cryptolight.strategy.macd import calculate_ema
from cryptolight.strategy.rsi import calculate_rsi

logger = logging.getLogger("cryptolight.strategy.score_based")

# 국면별 지표 가중치 및 매수 임계값
REGIME_WEIGHTS: dict[str, dict] = {
    "trending": {
        "rsi": 0.8, "rsi_dir": 0.8, "macd": 1.5, "macd_hist": 1.5,
        "bb": 0.5, "volume": 1.0, "buy_threshold": 55, "sell_threshold": 45,
    },
    "sideways": {
        "rsi": 1.2, "rsi_dir": 1.2, "macd": 0.5, "macd_hist": 0.5,
        "bb": 1.5, "volume": 1.0, "buy_threshold": 65, "sell_threshold": 55,
    },
    "volatile": {
        "rsi": 1.0, "rsi_dir": 1.0, "macd": 1.0, "macd_hist": 1.0,
        "bb": 1.0, "volume": 1.0, "buy_threshold": 75, "sell_threshold": 65,
    },
}
DEFAULT_WEIGHTS = REGIME_WEIGHTS["volatile"]

# 기본 점수 (가중치 적용 전)
BASE_SCORES = {
    "rsi": 25,
    "rsi_dir": 10,
    "macd": 25,
    "macd_hist": 10,
    "bb": 20,
    "volume": 10,
}


class ScoreBasedStrategy(BaseStrategy):
    """멀티팩터 스코어 기반 매매 전략.

    RSI, MACD, 볼린저밴드, 거래량을 종합하여 점수를 산출하고,
    시장 국면별 가중치를 적용하여 매매 판단.
    """

    def __init__(
        self,
        rsi_period: int = 14,
        rsi_oversold: float = 35.0,
        rsi_overbought: float = 65.0,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        bb_period: int = 20,
        bb_std_mult: float = 2.0,
        volume_period: int = 20,
        regime: str = "",
    ):
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.bb_period = bb_period
        self.bb_std_mult = bb_std_mult
        self.volume_period = volume_period
        self._regime = regime

    @property
    def regime(self) -> str:
        return self._regime

    @regime.setter
    def regime(self, value: str):
        self._regime = value

    def required_candle_count(self) -> int:
        return max(
            self.rsi_period + 2,
            self.macd_slow + self.macd_signal + 1,
            self.bb_period,
            self.volume_period + 1,
        )

    def _get_weights(self) -> dict:
        return REGIME_WEIGHTS.get(self._regime, DEFAULT_WEIGHTS)

    def _calc_rsi_scores(self, closes: list[float]) -> tuple[float, float, dict]:
        """RSI 관련 매수/매도 점수 계산. (buy_score, sell_score, indicators)"""
        rsi = calculate_rsi(closes, self.rsi_period)
        prev_rsi = calculate_rsi(closes[:-1], self.rsi_period)

        if rsi is None:
            return 0, 0, {}

        buy_score = 0.0
        sell_score = 0.0

        # RSI 과매도/과매수
        if rsi <= self.rsi_oversold:
            buy_score += BASE_SCORES["rsi"]
        if rsi >= self.rsi_overbought:
            sell_score += BASE_SCORES["rsi"]

        # RSI 방향성
        if prev_rsi is not None:
            if rsi > prev_rsi:  # 반등 시작
                buy_score += BASE_SCORES["rsi_dir"]
            if rsi < prev_rsi:  # 하락 시작
                sell_score += BASE_SCORES["rsi_dir"]

        indicators = {"rsi": round(rsi, 2)}
        if prev_rsi is not None:
            indicators["prev_rsi"] = round(prev_rsi, 2)

        return buy_score, sell_score, indicators

    def _calc_macd_scores(self, closes: list[float]) -> tuple[float, float, dict]:
        """MACD 관련 매수/매도 점수 계산."""
        ema_fast = calculate_ema(closes, self.macd_fast)
        ema_slow = calculate_ema(closes, self.macd_slow)

        if len(ema_slow) < 2:
            return 0, 0, {}

        offset = len(ema_fast) - len(ema_slow)
        ema_fast_aligned = ema_fast[offset:]
        macd_line = [f - s for f, s in zip(ema_fast_aligned, ema_slow)]
        signal_line = calculate_ema(macd_line, self.macd_signal)

        if len(signal_line) < 2:
            return 0, 0, {}

        macd_aligned = macd_line[len(macd_line) - len(signal_line):]
        histogram = [m - s for m, s in zip(macd_aligned, signal_line)]

        macd = macd_aligned[-1]
        signal_val = signal_line[-1]
        hist = histogram[-1]
        prev_hist = histogram[-2] if len(histogram) >= 2 else 0

        buy_score = 0.0
        sell_score = 0.0

        # MACD vs Signal
        if macd > signal_val:
            buy_score += BASE_SCORES["macd"]
        if macd < signal_val:
            sell_score += BASE_SCORES["macd"]

        # 히스토그램 모멘텀
        if hist > prev_hist:
            buy_score += BASE_SCORES["macd_hist"]
        if hist < prev_hist:
            sell_score += BASE_SCORES["macd_hist"]

        indicators = {
            "macd": round(macd, 2),
            "macd_signal": round(signal_val, 2),
            "histogram": round(hist, 2),
        }
        return buy_score, sell_score, indicators

    def _calc_bb_scores(self, closes: list[float]) -> tuple[float, float, dict]:
        """볼린저밴드 관련 매수/매도 점수 계산."""
        if len(closes) < self.bb_period:
            return 0, 0, {}

        recent = closes[-self.bb_period:]
        close = recent[-1]
        middle = statistics.mean(recent)
        std = statistics.pstdev(recent)
        upper = middle + self.bb_std_mult * std
        lower = middle - self.bb_std_mult * std
        pct_b = (close - lower) / (upper - lower) if upper != lower else 0.5

        buy_score = 0.0
        sell_score = 0.0

        if close <= lower or pct_b < 0.2:
            buy_score += BASE_SCORES["bb"]
        if close >= upper or pct_b > 0.8:
            sell_score += BASE_SCORES["bb"]

        indicators = {
            "bb_upper": round(upper, 0),
            "bb_lower": round(lower, 0),
            "pct_b": round(pct_b, 4),
        }
        return buy_score, sell_score, indicators

    def _calc_volume_scores(self, candles: list[Candle]) -> tuple[float, float, dict]:
        """거래량 관련 매수/매도 점수 계산."""
        if len(candles) < self.volume_period + 1:
            return 0, 0, {}

        volumes = [c.volume for c in candles[-(self.volume_period + 1):-1]]
        current_volume = candles[-1].volume
        avg_volume = statistics.mean(volumes) if volumes else 0

        if avg_volume <= 0:
            return 0, 0, {}

        volume_ratio = current_volume / avg_volume
        score = BASE_SCORES["volume"] if volume_ratio >= 1.0 else 0.0

        indicators = {"volume_ratio": round(volume_ratio, 2)}
        return score, score, indicators  # 거래량은 매수/매도 동일

    def analyze(self, candles: list[Candle]) -> Signal:
        if len(candles) < self.required_candle_count():
            return Signal(
                action="hold",
                symbol="",
                reason=f"캔들 부족 ({len(candles)}/{self.required_candle_count()})",
            )

        closes = [c.close for c in candles]
        weights = self._get_weights()

        # 각 지표별 점수 계산
        rsi_buy, rsi_sell, rsi_ind = self._calc_rsi_scores(closes)
        macd_buy, macd_sell, macd_ind = self._calc_macd_scores(closes)
        bb_buy, bb_sell, bb_ind = self._calc_bb_scores(closes)
        vol_buy, vol_sell, vol_ind = self._calc_volume_scores(candles)

        # 국면별 가중치 적용
        buy_score = (
            rsi_buy * weights["rsi"]
            + (rsi_buy / BASE_SCORES["rsi"] * BASE_SCORES["rsi_dir"] if rsi_buy > 0 else 0) * (weights["rsi_dir"] - weights["rsi"])  # rsi_dir 보정
            + macd_buy * weights["macd"]
            + vol_buy * weights["volume"]
            + bb_buy * weights["bb"]
        )

        sell_score = (
            rsi_sell * weights["rsi"]
            + (rsi_sell / BASE_SCORES["rsi"] * BASE_SCORES["rsi_dir"] if rsi_sell > 0 else 0) * (weights["rsi_dir"] - weights["rsi"])
            + macd_sell * weights["macd"]
            + vol_sell * weights["volume"]
            + bb_sell * weights["bb"]
        )

        # 정확한 점수: 각 팩터별 개별 점수를 합산
        raw_buy = rsi_buy + macd_buy + bb_buy + vol_buy
        raw_sell = rsi_sell + macd_sell + bb_sell + vol_sell

        # 가중치 적용 후 정규화 (최대 100점 기준)
        max_weighted = sum(
            BASE_SCORES[k] * weights[k]
            for k in ["rsi", "rsi_dir", "macd", "macd_hist", "bb", "volume"]
        )
        buy_normalized = min(buy_score / max_weighted * 100, 100) if max_weighted > 0 else 0
        sell_normalized = min(sell_score / max_weighted * 100, 100) if max_weighted > 0 else 0

        buy_threshold = weights["buy_threshold"]
        sell_threshold = weights["sell_threshold"]

        # 지표 통합
        indicators = {**rsi_ind, **macd_ind, **bb_ind, **vol_ind}
        indicators["buy_score"] = round(raw_buy, 1)
        indicators["sell_score"] = round(raw_sell, 1)
        indicators["regime"] = self._regime or "default"

        regime_label = self._regime or "default"

        # 매수 판단
        if buy_normalized >= buy_threshold and buy_normalized > sell_normalized:
            confidence = round(min(buy_normalized / 100, 1.0), 2)
            # 어떤 지표가 활성화됐는지 설명
            factors = []
            if rsi_buy > 0:
                factors.append(f"RSI {rsi_ind.get('rsi', '?')}")
            if macd_buy > 0:
                factors.append("MACD 상승")
            if bb_buy > 0:
                factors.append("BB 하단")
            if vol_buy > 0:
                factors.append("거래량 확인")

            return Signal(
                action="buy",
                symbol="",
                reason=f"스코어 매수 {raw_buy:.0f}점 ({', '.join(factors)}) [{regime_label}]",
                confidence=confidence,
                indicators=indicators,
            )

        # 매도 판단
        if sell_normalized >= sell_threshold and sell_normalized > buy_normalized:
            confidence = round(min(sell_normalized / 100, 1.0), 2)
            factors = []
            if rsi_sell > 0:
                factors.append(f"RSI {rsi_ind.get('rsi', '?')}")
            if macd_sell > 0:
                factors.append("MACD 하락")
            if bb_sell > 0:
                factors.append("BB 상단")
            if vol_sell > 0:
                factors.append("거래량 확인")

            return Signal(
                action="sell",
                symbol="",
                reason=f"스코어 매도 {raw_sell:.0f}점 ({', '.join(factors)}) [{regime_label}]",
                confidence=confidence,
                indicators=indicators,
            )

        # 관망
        return Signal(
            action="hold",
            symbol="",
            reason=f"스코어 미달: 매수 {raw_buy:.0f}점 / 매도 {raw_sell:.0f}점 [{regime_label}]",
            confidence=0.0,
            indicators=indicators,
        )
