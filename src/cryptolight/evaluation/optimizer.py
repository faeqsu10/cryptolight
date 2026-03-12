"""파라미터 최적화기 — Random Search + WalkForward 검증"""

import logging
import random
from dataclasses import dataclass, field

from cryptolight.backtest.engine import BacktestEngine
from cryptolight.backtest.walk_forward import WalkForwardValidator
from cryptolight.exchange.base import Candle
from cryptolight.strategy import create_strategy

logger = logging.getLogger("cryptolight.evaluation.optimizer")

# 전략별 파라미터 탐색 범위
PARAM_RANGES: dict[str, dict] = {
    "rsi": {
        "period": (5, 30),
        "overbought": (60, 85),
        "oversold": (15, 40),
    },
    "macd": {
        "fast": (8, 16),
        "slow": (20, 35),
        "signal_period": (5, 14),
    },
    "bollinger": {
        "period": (10, 30),
        "std_mult": (1.5, 3.0),
    },
    "volatility_breakout": {
        "k": (0.3, 0.8),
    },
    "score": {
        "rsi_period": (10, 20),
        "rsi_oversold": (25, 40),
        "rsi_overbought": (60, 75),
        "macd_fast": (8, 16),
        "macd_slow": (20, 35),
        "macd_signal": (5, 14),
        "bb_period": (14, 30),
        "bb_std_mult": (1.5, 3.0),
        "volume_period": (10, 30),
    },
}


@dataclass
class OptimizationResult:
    strategy: str
    best_params: dict = field(default_factory=dict)
    best_sharpe: float = -999.0
    best_return_pct: float = 0.0
    best_wf_consistency: float = 0.0
    trials_run: int = 0
    valid_trials: int = 0
    all_results: list[dict] = field(default_factory=list)

    def summary_text(self) -> str:
        if self.valid_trials == 0:
            return f"{self.strategy}: 유효한 결과 없음 ({self.trials_run}회 시도)"
        return (
            f"{self.strategy}: 최적 Sharpe={self.best_sharpe:.3f}, "
            f"수익={self.best_return_pct:+.2f}%, WF={self.best_wf_consistency:.0f}%, "
            f"파라미터={self.best_params}, "
            f"유효={self.valid_trials}/{self.trials_run}회"
        )


class ParameterOptimizer:
    """Random Search + WalkForward로 전략 파라미터를 최적화한다."""

    def __init__(
        self,
        initial_balance: float = 1_000_000,
        order_amount: float = 50_000,
        n_folds: int = 3,
        min_wf_consistency: float = 50.0,
        max_overfit_ratio: float = 3.0,
        min_trades_per_fold: int = 3,
        slippage_pct: float = 0.0,
        spread_pct: float = 0.0,
    ):
        self.initial_balance = initial_balance
        self.order_amount = order_amount
        self.n_folds = n_folds
        self.min_wf_consistency = min_wf_consistency
        self.max_overfit_ratio = max_overfit_ratio
        self.min_trades_per_fold = min_trades_per_fold
        self.slippage_pct = slippage_pct
        self.spread_pct = spread_pct

    def optimize(
        self,
        strategy_name: str,
        candles: list[Candle],
        n_trials: int = 50,
        seed: int | None = None,
    ) -> OptimizationResult:
        """전략의 파라미터를 Random Search로 최적화한다."""
        if strategy_name not in PARAM_RANGES:
            logger.warning("파라미터 범위 미정의: %s", strategy_name)
            return OptimizationResult(strategy=strategy_name)

        if seed is not None:
            random.seed(seed)

        ranges = PARAM_RANGES[strategy_name]
        result = OptimizationResult(strategy=strategy_name)

        for trial in range(n_trials):
            params = self._sample_params(ranges)
            result.trials_run += 1

            try:
                trial_result = self._evaluate_params(strategy_name, params, candles)
            except Exception:
                logger.debug("Trial %d 실패: %s %s", trial, strategy_name, params)
                continue

            if trial_result is None:
                continue

            # 과적합 필터
            if not self._passes_filters(trial_result):
                continue

            result.valid_trials += 1
            result.all_results.append(trial_result)

            sharpe = trial_result.get("sharpe", -999)
            if sharpe > result.best_sharpe:
                result.best_sharpe = round(sharpe, 3)
                result.best_params = params
                result.best_return_pct = round(trial_result.get("total_return_pct", 0), 2)
                result.best_wf_consistency = round(trial_result.get("wf_consistency", 0), 1)

        logger.info(
            "최적화 완료: %s — %d/%d 유효, 최적 Sharpe=%.3f",
            strategy_name, result.valid_trials, result.trials_run, result.best_sharpe,
        )
        return result

    def evaluate_params(
        self,
        strategy_name: str,
        params: dict,
        candles: list[Candle],
    ) -> dict | None:
        """특정 파라미터 조합의 백테스트 + Walk-Forward 결과를 평가한다."""
        return self._evaluate_params(strategy_name, params, candles)

    def _sample_params(self, ranges: dict) -> dict:
        """파라미터 범위에서 랜덤 샘플링."""
        params = {}
        for name, (lo, hi) in ranges.items():
            if isinstance(lo, int) and isinstance(hi, int):
                params[name] = random.randint(lo, hi)
            else:
                params[name] = round(random.uniform(lo, hi), 2)
        return params

    def _evaluate_params(
        self, strategy_name: str, params: dict, candles: list[Candle]
    ) -> dict | None:
        """파라미터 조합을 백테스트 + WalkForward로 평가."""
        strategy = create_strategy(strategy_name, **params)

        if len(candles) < strategy.required_candle_count() * 2:
            return None

        # 백테스트
        engine = BacktestEngine(
            strategy=create_strategy(strategy_name, **params),
            initial_balance=self.initial_balance,
            order_amount=self.order_amount,
            slippage_pct=self.slippage_pct,
            spread_pct=self.spread_pct,
        )
        bt_result = engine.run(candles)

        if bt_result.total_trades < self.min_trades_per_fold * self.n_folds:
            return None

        # Walk-Forward 검증
        wf_validator = WalkForwardValidator(
            strategy=create_strategy(strategy_name, **params),
            initial_balance=self.initial_balance,
            order_amount=self.order_amount,
            slippage_pct=self.slippage_pct,
            spread_pct=self.spread_pct,
        )
        wf_result = wf_validator.run(candles, n_folds=self.n_folds)

        if not wf_result.folds:
            return None

        sharpe = bt_result.sharpe_ratio if bt_result.total_trades >= 2 else 0.0

        return {
            "params": params,
            "total_return_pct": bt_result.total_return_pct,
            "total_trades": bt_result.total_trades,
            "sharpe": sharpe,
            "wf_consistency": wf_result.consistency,
            "wf_overfit_ratio": wf_result.overfitting_ratio,
            "wf_avg_oos": wf_result.avg_out_sample_return,
        }

    def _passes_filters(self, trial_result: dict) -> bool:
        """과적합 필터를 통과하는지 확인."""
        # WalkForward consistency 필터
        if trial_result.get("wf_consistency", 0) < self.min_wf_consistency:
            return False
        # 과적합 비율 필터
        overfit = trial_result.get("wf_overfit_ratio", float("inf"))
        if abs(overfit) > self.max_overfit_ratio:
            return False
        return True
