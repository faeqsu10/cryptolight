from cryptolight.strategy.base import BaseStrategy, Signal
from cryptolight.strategy.rsi import RSIStrategy
from cryptolight.strategy.volatility_breakout import VolatilityBreakoutStrategy

__all__ = ["BaseStrategy", "Signal", "RSIStrategy", "VolatilityBreakoutStrategy", "create_strategy"]


def create_strategy(name: str, **kwargs) -> BaseStrategy:
    if name == "rsi":
        return RSIStrategy(**kwargs)
    elif name == "volatility_breakout":
        return VolatilityBreakoutStrategy(**kwargs)
    raise ValueError(f"Unknown strategy: {name}")
