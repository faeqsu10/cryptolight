"""앙상블 전략 — 다수결 투표"""

from collections import Counter

from cryptolight.exchange.base import Candle
from cryptolight.strategy.base import BaseStrategy, Signal


class EnsembleStrategy(BaseStrategy):
    def __init__(self, strategies: list[BaseStrategy]):
        self.strategies = strategies

    def get_tunable_params(self) -> dict:
        """앙상블은 개별 전략이 아닌 하위 전략들의 조합이므로 직접 튜닝 대상 아님."""
        return {}

    def required_candle_count(self) -> int:
        return max(s.required_candle_count() for s in self.strategies)

    def analyze(self, candles: list[Candle]) -> Signal:
        signals: list[Signal] = []
        for strategy in self.strategies:
            signals.append(strategy.analyze(candles))

        total = len(signals)
        votes = Counter(s.action for s in signals)

        # 전략 이름별 action 매핑
        indicators: dict[str, str] = {}
        for strategy, signal in zip(self.strategies, signals):
            name = type(strategy).__name__.replace("Strategy", "").lower()
            indicators[name] = signal.action

        # 동의한 전략 이름 추출 함수
        def _strategy_names_for(action: str) -> list[str]:
            names = []
            for strategy, signal in zip(self.strategies, signals):
                if signal.action == action:
                    names.append(type(strategy).__name__.replace("Strategy", ""))
            return names

        # 평균 confidence (해당 action에 투표한 전략들의 평균)
        def _avg_confidence(action: str) -> float:
            confs = [s.confidence for s in signals if s.action == action]
            return sum(confs) / len(confs) if confs else 0.0

        # 2/3 이상 동의
        threshold_2_3 = total * 2 / 3
        for action, count in votes.most_common():
            if count >= threshold_2_3:
                names = _strategy_names_for(action)
                ratio = count / total
                confidence = round(ratio * _avg_confidence(action), 4)
                indicators["vote"] = f"{count}/{total} {action}"
                return Signal(
                    action=action,
                    symbol="",
                    reason=f"앙상블 {count}/{total} {action} ({', '.join(names)})",
                    confidence=confidence,
                    indicators=indicators,
                )

        # 과반수
        for action, count in votes.most_common():
            if count > total / 2:
                names = _strategy_names_for(action)
                ratio = count / total
                confidence = round(ratio * _avg_confidence(action) * 0.7, 4)
                indicators["vote"] = f"{count}/{total} {action}"
                return Signal(
                    action=action,
                    symbol="",
                    reason=f"앙상블 {count}/{total} {action} ({', '.join(names)})",
                    confidence=confidence,
                    indicators=indicators,
                )

        # 동률 → hold
        indicators["vote"] = "동률"
        return Signal(
            action="hold",
            symbol="",
            reason="앙상블 동률 — hold",
            indicators=indicators,
        )
