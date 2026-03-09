"""Walk-Forward Validation — 과적합 방지 백테스트"""

import copy
import logging
from dataclasses import dataclass, field

from cryptolight.backtest.engine import BacktestEngine, BacktestResult
from cryptolight.exchange.base import Candle
from cryptolight.strategy.base import BaseStrategy

logger = logging.getLogger("cryptolight.backtest.walk_forward")


@dataclass
class WalkForwardFold:
    fold: int
    in_sample_size: int
    out_sample_size: int
    in_sample_result: BacktestResult
    out_sample_result: BacktestResult


@dataclass
class WalkForwardResult:
    folds: list[WalkForwardFold] = field(default_factory=list)
    avg_in_sample_return: float = 0.0
    avg_out_sample_return: float = 0.0
    overfitting_ratio: float = 0.0  # IS/OOS 수익률 비율 — 높으면 과적합
    consistency: float = 0.0  # OOS에서 양수 수익률인 구간 비율

    def summary_text(self) -> str:
        lines = [
            "=== Walk-Forward Validation ===",
            f"구간 수: {len(self.folds)}",
            f"평균 In-Sample 수익률: {self.avg_in_sample_return:+.2f}%",
            f"평균 Out-of-Sample 수익률: {self.avg_out_sample_return:+.2f}%",
            f"과적합 비율 (IS/OOS): {self.overfitting_ratio:.2f}x",
            f"OOS 일관성: {self.consistency:.0f}%",
            "",
        ]
        for f in self.folds:
            lines.append(
                f"  Fold {f.fold}: IS={f.in_sample_result.total_return_pct:+.2f}% "
                f"OOS={f.out_sample_result.total_return_pct:+.2f}% "
                f"(IS {f.in_sample_size}개, OOS {f.out_sample_size}개)"
            )
        return "\n".join(lines)


class WalkForwardValidator:
    """Walk-Forward Validation을 수행한다."""

    def __init__(
        self,
        strategy: BaseStrategy,
        initial_balance: float = 1_000_000,
        order_amount: float = 50_000,
        commission_rate: float = 0.0005,
        slippage_pct: float = 0.0,
        spread_pct: float = 0.0,
        train_ratio: float = 0.7,
    ):
        self.strategy = strategy
        self.initial_balance = initial_balance
        self.order_amount = order_amount
        self.commission_rate = commission_rate
        self.slippage_pct = slippage_pct
        self.spread_pct = spread_pct
        self.train_ratio = train_ratio

    def run(self, candles: list[Candle], n_folds: int = 5) -> WalkForwardResult:
        """N개 구간으로 Walk-Forward Validation 실행."""
        total = len(candles)
        fold_size = total // n_folds

        if fold_size < self.strategy.required_candle_count() * 2:
            logger.warning("캔들 부족: fold당 %d개 (최소 %d 필요)", fold_size, self.strategy.required_candle_count() * 2)
            return WalkForwardResult()

        folds = []
        for i in range(n_folds):
            start = i * fold_size
            end = min(start + fold_size, total)
            fold_candles = candles[start:end]

            split = int(len(fold_candles) * self.train_ratio)
            in_sample = fold_candles[:split]
            out_sample = fold_candles[split:]

            if len(in_sample) < self.strategy.required_candle_count() or len(out_sample) < self.strategy.required_candle_count():
                continue

            fold_strategy = copy.deepcopy(self.strategy)
            is_engine = BacktestEngine(
                strategy=fold_strategy,
                initial_balance=self.initial_balance,
                order_amount=self.order_amount,
                commission_rate=self.commission_rate,
                slippage_pct=self.slippage_pct,
                spread_pct=self.spread_pct,
            )
            is_result = is_engine.run(in_sample)

            oos_strategy = copy.deepcopy(self.strategy)
            oos_engine = BacktestEngine(
                strategy=oos_strategy,
                initial_balance=self.initial_balance,
                order_amount=self.order_amount,
                commission_rate=self.commission_rate,
                slippage_pct=self.slippage_pct,
                spread_pct=self.spread_pct,
            )
            oos_result = oos_engine.run(out_sample)

            folds.append(WalkForwardFold(
                fold=i + 1,
                in_sample_size=len(in_sample),
                out_sample_size=len(out_sample),
                in_sample_result=is_result,
                out_sample_result=oos_result,
            ))

        if not folds:
            return WalkForwardResult()

        avg_is = sum(f.in_sample_result.total_return_pct for f in folds) / len(folds)
        avg_oos = sum(f.out_sample_result.total_return_pct for f in folds) / len(folds)
        # IS/OOS 비율: 부호 보존하여 OOS 손실 시 음수 반환
        if avg_oos != 0:
            overfit = avg_is / avg_oos
        else:
            overfit = float("inf") if avg_is > 0 else 0.0
        consistency = sum(1 for f in folds if f.out_sample_result.total_return_pct > 0) / len(folds) * 100

        result = WalkForwardResult(
            folds=folds,
            avg_in_sample_return=round(avg_is, 2),
            avg_out_sample_return=round(avg_oos, 2),
            overfitting_ratio=round(overfit, 2),
            consistency=round(consistency, 1),
        )

        logger.info(
            "Walk-Forward 완료: %d folds, IS=%.2f%%, OOS=%.2f%%, 과적합=%.2fx",
            len(folds), avg_is, avg_oos, overfit,
        )

        return result
