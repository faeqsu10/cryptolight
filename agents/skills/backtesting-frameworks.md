---
name: backtesting-frameworks
description: 암호화폐 전략 백테스트 시스템 구축. Look-ahead bias 방지, 현실적 비용 모델, walk-forward 분석 패턴 제공.
---

# 백테스트 프레임워크

## 벡터화 백테스터 (빠른 검증용)

```python
import pandas as pd
import numpy as np

class VectorizedBacktester:
    def __init__(self, initial_capital=1_000_000, commission=0.0005, slippage=0.0005):
        self.initial_capital = initial_capital
        self.commission = commission  # 업비트 0.05%
        self.slippage = slippage

    def run(self, prices: pd.DataFrame, signal_func) -> dict:
        signals = signal_func(prices).shift(1).fillna(0)  # shift로 look-ahead 방지
        returns = prices["close"].pct_change()
        position_changes = signals.diff().abs()
        trading_costs = position_changes * (self.commission + self.slippage)
        strategy_returns = signals * returns - trading_costs
        equity = (1 + strategy_returns).cumprod() * self.initial_capital

        return {
            "equity": equity,
            "returns": strategy_returns,
            "signals": signals,
            "metrics": self._metrics(strategy_returns, equity),
        }

    def _metrics(self, returns, equity) -> dict:
        total_return = (equity.iloc[-1] / self.initial_capital) - 1
        annual_return = (1 + total_return) ** (365 / len(returns)) - 1  # 코인: 365일
        annual_vol = returns.std() * np.sqrt(365)
        sharpe = annual_return / annual_vol if annual_vol > 0 else 0
        rolling_max = equity.cummax()
        max_dd = ((equity - rolling_max) / rolling_max).min()
        wins = (returns > 0).sum()
        total = (returns != 0).sum()

        return {
            "total_return": total_return,
            "annual_return": annual_return,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_dd,
            "win_rate": wins / total if total > 0 else 0,
            "profit_factor": returns[returns > 0].sum() / abs(returns[returns < 0].sum()) if returns[returns < 0].sum() != 0 else float("inf"),
            "num_trades": int(total),
        }
```

## 성과 지표 계산

```python
def calculate_metrics(returns: pd.Series, rf_rate=0.02) -> dict:
    ann = 365  # 코인 시장 연간 거래일
    total_return = (1 + returns).prod() - 1
    annual_return = (1 + total_return) ** (ann / len(returns)) - 1
    annual_vol = returns.std() * np.sqrt(ann)
    sharpe = (annual_return - rf_rate) / annual_vol if annual_vol > 0 else 0

    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(ann)
    sortino = (annual_return - rf_rate) / downside_vol if downside_vol > 0 else 0

    equity = (1 + returns).cumprod()
    max_dd = ((equity - equity.cummax()) / equity.cummax()).min()
    calmar = annual_return / abs(max_dd) if max_dd != 0 else 0

    return {
        "total_return": total_return,
        "annual_return": annual_return,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "max_drawdown": max_dd,
        "calmar_ratio": calmar,
        "win_rate": (returns > 0).sum() / (returns != 0).sum(),
    }
```

## 주의사항

- 코인은 연간 365일 (주식 252일 아님)
- 수수료: 업비트 0.05%, 바이낸스 0.1%
- 시그널은 반드시 `.shift(1)` 적용 (look-ahead 방지)
- 최소 6개월 이상 데이터로 테스트
- Out-of-sample 20% 이상 확보
