from cryptolight.strategy.base import BaseStrategy, Signal
from cryptolight.strategy.bollinger import BollingerStrategy
from cryptolight.strategy.ensemble import EnsembleStrategy
from cryptolight.strategy.macd import MACDStrategy
from cryptolight.strategy.rsi import RSIStrategy
from cryptolight.strategy.score_based import ScoreBasedStrategy
from cryptolight.strategy.volatility_breakout import VolatilityBreakoutStrategy
from cryptolight.strategy.volume_filter import VolumeFilter

__all__ = [
    "BaseStrategy",
    "Signal",
    "RSIStrategy",
    "VolatilityBreakoutStrategy",
    "MACDStrategy",
    "BollingerStrategy",
    "EnsembleStrategy",
    "ScoreBasedStrategy",
    "VolumeFilter",
    "create_strategy",
    "STRATEGY_REGISTRY",
]

STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "rsi": RSIStrategy,
    "macd": MACDStrategy,
    "bollinger": BollingerStrategy,
    "volatility_breakout": VolatilityBreakoutStrategy,
    "score": ScoreBasedStrategy,
}


def create_strategy(name: str, **kwargs) -> BaseStrategy:
    if name == "ensemble":
        strategy_names = kwargs.pop("strategy_names", ["rsi", "macd", "bollinger"])
        strategies = [create_strategy(n) for n in strategy_names]
        return EnsembleStrategy(strategies=strategies)

    cls = STRATEGY_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown strategy: {name}")
    return cls(**kwargs)
