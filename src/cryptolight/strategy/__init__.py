from cryptolight.strategy.base import BaseStrategy, Signal
from cryptolight.strategy.bollinger import BollingerStrategy
from cryptolight.strategy.ensemble import EnsembleStrategy
from cryptolight.strategy.macd import MACDStrategy
from cryptolight.strategy.rsi import RSIStrategy
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
    "VolumeFilter",
    "create_strategy",
]


def create_strategy(name: str, **kwargs) -> BaseStrategy:
    if name == "rsi":
        return RSIStrategy(**kwargs)
    elif name == "volatility_breakout":
        return VolatilityBreakoutStrategy(**kwargs)
    elif name == "macd":
        return MACDStrategy(**kwargs)
    elif name == "bollinger":
        return BollingerStrategy(**kwargs)
    elif name == "ensemble":
        strategy_names = kwargs.pop("strategy_names", ["rsi", "macd", "bollinger"])
        strategies = [create_strategy(n) for n in strategy_names]
        return EnsembleStrategy(strategies=strategies)
    raise ValueError(f"Unknown strategy: {name}")
