---
name: risk-metrics
description: 포트폴리오 리스크 지표 계산. VaR, CVaR, Sharpe, Sortino, drawdown 분석 패턴 제공.
---

# 리스크 지표 계산

## 핵심 지표 클래스

```python
import numpy as np
import pandas as pd
from scipy import stats

class RiskMetrics:
    def __init__(self, returns: pd.Series, rf_rate=0.02):
        self.returns = returns
        self.rf_rate = rf_rate
        self.ann = 365  # 코인 시장

    def var_historical(self, confidence=0.95) -> float:
        return -np.percentile(self.returns, (1 - confidence) * 100)

    def cvar(self, confidence=0.95) -> float:
        var = self.var_historical(confidence)
        return -self.returns[self.returns <= -var].mean()

    def max_drawdown(self) -> float:
        equity = (1 + self.returns).cumprod()
        return ((equity - equity.cummax()) / equity.cummax()).min()

    def sharpe_ratio(self) -> float:
        excess = self.returns.mean() * self.ann - self.rf_rate
        vol = self.returns.std() * np.sqrt(self.ann)
        return excess / vol if vol > 0 else 0

    def sortino_ratio(self) -> float:
        excess = self.returns.mean() * self.ann - self.rf_rate
        downside = self.returns[self.returns < 0].std() * np.sqrt(self.ann)
        return excess / downside if downside > 0 else 0

    def summary(self) -> dict:
        return {
            "sharpe": self.sharpe_ratio(),
            "sortino": self.sortino_ratio(),
            "max_drawdown": self.max_drawdown(),
            "var_95": self.var_historical(0.95),
            "cvar_95": self.cvar(0.95),
            "volatility": self.returns.std() * np.sqrt(self.ann),
            "skewness": stats.skew(self.returns),
            "kurtosis": stats.kurtosis(self.returns),
        }
```

## R-Multiple 추적

```python
@dataclass
class Trade:
    entry_price: float
    exit_price: float
    stop_loss: float
    side: str  # "long" / "short"

    @property
    def r_multiple(self) -> float:
        risk = abs(self.entry_price - self.stop_loss)
        if risk == 0:
            return 0
        pnl = (self.exit_price - self.entry_price) if self.side == "long" \
              else (self.entry_price - self.exit_price)
        return pnl / risk

def expectancy(trades: list[Trade]) -> float:
    r_values = [t.r_multiple for t in trades]
    wins = [r for r in r_values if r > 0]
    losses = [r for r in r_values if r <= 0]
    win_rate = len(wins) / len(r_values)
    return (win_rate * np.mean(wins)) - ((1 - win_rate) * abs(np.mean(losses)))
```

## 포지션 사이징 (2% 룰)

```python
def position_size(account_balance: float, risk_pct: float, entry: float, stop_loss: float) -> float:
    risk_amount = account_balance * risk_pct  # 예: 100만원 × 0.02 = 2만원
    risk_per_unit = abs(entry - stop_loss)
    if risk_per_unit == 0:
        return 0
    return risk_amount / risk_per_unit
```
