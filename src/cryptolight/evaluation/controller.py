"""적응형 컨트롤러 — 성과 기반 전략 자동 전환"""

import logging
from datetime import datetime

from cryptolight.evaluation.performance import PerformanceEvaluator
from cryptolight.storage.repository import TradeRepository

logger = logging.getLogger("cryptolight.evaluation.controller")


class AdaptiveController:
    """성과 평가 결과를 바탕으로 활성 전략을 자동 전환한다."""

    def __init__(
        self,
        repo: TradeRepository,
        min_sharpe_improvement: float = 0.5,
        cooldown_days: int = 7,
        rollback_loss_threshold: float = -5.0,
    ):
        self._repo = repo
        self.min_sharpe_improvement = min_sharpe_improvement
        self.cooldown_days = cooldown_days
        self.rollback_loss_threshold = rollback_loss_threshold

    def should_switch(
        self,
        current_strategy: str,
        arena_results: list[dict],
        evaluator: PerformanceEvaluator,
    ) -> dict:
        """전략 전환 여부를 판단한다.

        Returns:
            {
                "switch": bool,
                "from": str,
                "to": str | None,
                "reason": str,
            }
        """
        # 쿨다운 체크
        if self._in_cooldown():
            return {
                "switch": False,
                "from": current_strategy,
                "to": None,
                "reason": f"쿨다운 중 ({self.cooldown_days}일)",
            }

        # 현재 전략 성과 평가
        current_eval = evaluator.evaluate_strategy(current_strategy, days=7)
        current_sharpe = current_eval.get("sharpe_ratio", 0)

        # Arena 1위 전략 확인
        valid_candidates = [
            r for r in arena_results
            if r.get("wf_passed") and r["strategy"] != current_strategy
        ]

        if not valid_candidates:
            return {
                "switch": False,
                "from": current_strategy,
                "to": None,
                "reason": "WF 검증 통과한 대안 전략 없음",
            }

        best = valid_candidates[0]
        best_sharpe = best.get("sharpe", -999)

        # 전환 조건 1: 현재 전략 성과 부진
        current_poor = current_sharpe < 0

        # 전환 조건 2: 대안이 현재보다 충분히 우수
        improvement = best_sharpe - current_sharpe
        sufficient_improvement = improvement >= self.min_sharpe_improvement

        if current_poor and sufficient_improvement:
            reason = (
                f"현재({current_strategy}) Sharpe={current_sharpe:.3f} 부진, "
                f"대안({best['strategy']}) Sharpe={best_sharpe:.3f} 우수 "
                f"(개선폭={improvement:.3f})"
            )
            return {
                "switch": True,
                "from": current_strategy,
                "to": best["strategy"],
                "to_params": best.get("params", {}),
                "reason": reason,
            }

        if not current_poor:
            reason = f"현재({current_strategy}) Sharpe={current_sharpe:.3f} 양호"
        else:
            reason = (
                f"개선폭 부족: {improvement:.3f} < {self.min_sharpe_improvement} 기준"
            )

        return {
            "switch": False,
            "from": current_strategy,
            "to": None,
            "reason": reason,
        }

    def record_switch(self, from_strategy: str, to_strategy: str, reason: str) -> None:
        """전략 전환을 DB에 기록한다."""
        self._repo.record_strategy_switch(from_strategy, to_strategy, reason)
        logger.info("전략 전환 기록: %s → %s (%s)", from_strategy, to_strategy, reason)

    def get_switch_history(self, limit: int = 10) -> list[dict]:
        """최근 전략 전환 이력을 조회한다."""
        return self._repo.get_strategy_switches(limit)

    def check_rollback(
        self, current_strategy: str, evaluator: PerformanceEvaluator
    ) -> dict | None:
        """전환 후 성과가 나쁘면 롤백을 제안한다."""
        history = self.get_switch_history(limit=1)
        if not history:
            return None

        last_switch = history[0]
        switch_date = datetime.fromisoformat(last_switch["switched_at"])
        days_since = (datetime.now() - switch_date).days

        if days_since > 3:
            return None  # 3일 초과 시 롤백 판단 안 함

        # 전환 후 성과 평가
        post_eval = evaluator.evaluate_strategy(current_strategy, days=days_since or 1)
        if post_eval.get("status") == "insufficient_data":
            return None

        total_return = post_eval.get("total_return_pct", 0)
        if total_return < self.rollback_loss_threshold:
            return {
                "rollback": True,
                "from": current_strategy,
                "to": last_switch["from_strategy"],
                "reason": (
                    f"전환 후 {days_since}일간 수익률 {total_return:+.1f}% "
                    f"(기준: {self.rollback_loss_threshold}%)"
                ),
            }
        return None

    def _in_cooldown(self) -> bool:
        """최근 전환으로부터 쿨다운 기간 내인지 확인."""
        history = self.get_switch_history(limit=1)
        if not history:
            return False
        last_switch = history[0]
        switch_date = datetime.fromisoformat(last_switch["switched_at"])
        return (datetime.now() - switch_date).days < self.cooldown_days
