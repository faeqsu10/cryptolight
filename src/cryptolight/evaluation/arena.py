"""전략 경기장 — 여러 전략을 백테스트로 비교 순위 매김"""

import logging
from datetime import datetime

from cryptolight.backtest.engine import BacktestEngine
from cryptolight.backtest.walk_forward import WalkForwardValidator
from cryptolight.exchange.base import Candle
from cryptolight.strategy import create_strategy

logger = logging.getLogger("cryptolight.evaluation.arena")

STRATEGY_NAMES = ["rsi", "macd", "bollinger", "volatility_breakout"]


class StrategyArena:
    """여러 전략을 백테스트하여 순위를 매긴다."""

    def __init__(
        self,
        initial_balance: float = 1_000_000,
        order_amount: float = 50_000,
        min_wf_consistency: float = 50.0,
        n_folds: int = 3,
    ):
        self.initial_balance = initial_balance
        self.order_amount = order_amount
        self.min_wf_consistency = min_wf_consistency
        self.n_folds = n_folds

    def compete(
        self,
        candles: list[Candle],
        strategy_configs: list[dict] | None = None,
    ) -> list[dict]:
        """모든 전략을 백테스트하고 순위를 매긴다.

        Args:
            candles: 백테스트용 캔들 데이터
            strategy_configs: [{"name": "rsi", "params": {...}}, ...] 또는 None (기본 전략)

        Returns:
            순위별 정렬된 결과 리스트
        """
        if strategy_configs is None:
            strategy_configs = [{"name": name, "params": {}} for name in STRATEGY_NAMES]

        results = []
        for config in strategy_configs:
            name = config["name"]
            params = config.get("params", {})
            try:
                result = self._evaluate_strategy(name, params, candles)
                results.append(result)
            except Exception:
                logger.exception("전략 평가 실패: %s", name)

        # Sharpe 기준 내림차순 정렬
        results.sort(key=lambda x: x.get("sharpe", -999), reverse=True)

        # 순위 부여
        for i, r in enumerate(results):
            r["rank"] = i + 1

        return results

    def _evaluate_strategy(
        self, name: str, params: dict, candles: list[Candle]
    ) -> dict:
        """단일 전략을 백테스트 + Walk-Forward 검증."""
        strategy = create_strategy(name, **params)

        if len(candles) < strategy.required_candle_count() * 2:
            return {
                "strategy": name,
                "params": params,
                "status": "insufficient_data",
                "sharpe": -999,
            }

        # 백테스트
        engine = BacktestEngine(
            strategy=strategy,
            initial_balance=self.initial_balance,
            order_amount=self.order_amount,
        )
        bt_result = engine.run(candles)

        # Walk-Forward 검증
        wf_validator = WalkForwardValidator(
            strategy=create_strategy(name, **params),
            initial_balance=self.initial_balance,
            order_amount=self.order_amount,
        )
        wf_result = wf_validator.run(candles, n_folds=self.n_folds)

        # Sharpe 계산 (백테스트 결과 기반)
        sharpe = self._calc_sharpe_from_result(bt_result)

        return {
            "strategy": name,
            "params": params,
            "status": "evaluated",
            "total_return_pct": bt_result.total_return_pct,
            "trade_count": bt_result.total_trades,
            "sharpe": round(sharpe, 3),
            "wf_consistency": wf_result.consistency,
            "wf_avg_oos_return": wf_result.avg_out_sample_return,
            "wf_passed": wf_result.consistency >= self.min_wf_consistency,
            "evaluated_at": datetime.now().isoformat(),
        }

    def _calc_sharpe_from_result(self, result) -> float:
        """백테스트 결과에서 Sharpe ratio를 반환한다."""
        if result.total_trades < 2:
            return 0.0
        return result.sharpe_ratio

    def summary_text(self, results: list[dict]) -> str:
        """경기장 결과 요약 텍스트."""
        if not results:
            return "경기장 결과 없음"

        lines = ["=== Strategy Arena ==="]
        for r in results:
            if r["status"] == "insufficient_data":
                lines.append(f"  #{r.get('rank', '?')} {r['strategy']}: 데이터 부족")
            else:
                wf_mark = "O" if r.get("wf_passed") else "X"
                lines.append(
                    f"  #{r['rank']} {r['strategy']}: "
                    f"수익={r['total_return_pct']:+.2f}%, "
                    f"Sharpe={r['sharpe']:.3f}, "
                    f"WF={r['wf_consistency']:.0f}%[{wf_mark}], "
                    f"거래={r['trade_count']}건"
                )
        return "\n".join(lines)
