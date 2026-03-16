"""Self-improvement and parameter tuning helpers extracted from main."""

from __future__ import annotations

from datetime import datetime
import html as html_mod
import logging
from typing import Any, Callable

from cryptolight.evaluation import AdaptiveController, ParameterOptimizer, PerformanceEvaluator, StrategyArena


def self_improvement_job(
    client,
    repo,
    bot,
    settings,
    *,
    logger: logging.Logger,
    get_effective_strategy_name: Callable[[Any], str],
    load_active_strategy_parameters: Callable[..., dict],
    set_active_strategy_name: Callable[[str], None],
) -> None:
    """Run the weekly strategy review and optional strategy switch."""

    if not settings.enable_auto_optimization:
        return

    try:
        current_strategy = get_effective_strategy_name(settings)
        evaluator = PerformanceEvaluator(repo)
        perf_summary = evaluator.summary_text(days=settings.arena_lookback_days)
        logger.info("자기개선 루프 시작")
        for line in perf_summary.splitlines():
            logger.info("%s", line)

        symbol = settings.symbol_list[0] if settings.symbol_list else "KRW-BTC"
        candles = client.get_candles(symbol, interval="day", count=settings.arena_lookback_days)

        arena = StrategyArena(
            initial_balance=settings.paper_initial_balance,
            order_amount=settings.max_order_amount_krw,
            n_folds=3,
            slippage_pct=settings.backtest_slippage_pct,
            spread_pct=settings.backtest_spread_pct,
            candle_interval=settings.candle_interval,
        )
        arena_results = arena.compete(candles)
        arena_text = arena.summary_text(arena_results)
        logger.info(arena_text)

        controller = AdaptiveController(
            repo=repo,
            min_sharpe_improvement=settings.min_sharpe_improvement,
            cooldown_days=settings.switch_cooldown_days,
        )
        switch_decision = controller.should_switch(current_strategy, arena_results, evaluator)
        logger.info("전환 판단: %s", switch_decision["reason"])

        if switch_decision["switch"]:
            controller.record_switch(
                switch_decision["from"],
                switch_decision["to"],
                switch_decision["reason"],
            )
            set_active_strategy_name(switch_decision["to"])
            load_active_strategy_parameters(repo, settings, logger)
            msg = (
                f"전략 전환: {switch_decision['from']} → {switch_decision['to']}\n"
                f"사유: {switch_decision['reason']}"
            )
            logger.warning(msg)
            if bot:
                bot.send_message(f"<b>전략 자동 전환</b>\n<pre>{html_mod.escape(msg)}</pre>")

        active_strategy = get_effective_strategy_name(settings)
        rollback = controller.check_rollback(active_strategy, evaluator)
        if rollback:
            logger.warning("롤백 제안: %s", rollback["reason"])
            if bot:
                bot.send_message(
                    f"<b>롤백 제안</b>\n"
                    f"{html_mod.escape(rollback['from'])} → {html_mod.escape(rollback['to'])}\n"
                    f"사유: {html_mod.escape(rollback['reason'])}"
                )

        if bot:
            bot.send_message(
                f"<b>자기개선 루프 완료</b>\n<pre>{html_mod.escape(arena_text)}</pre>\n"
                f"전환 판단: {html_mod.escape(switch_decision['reason'])}"
            )
    except Exception:
        logger.exception("자기개선 루프 실행 중 에러")


def run_parameter_tuning(
    repo,
    settings,
    strategy_name: str,
    candles,
    *,
    logger: logging.Logger,
    param_ranges: dict[str, Any],
    bot=None,
    build_strategy_instance: Callable[..., Any],
    get_effective_strategy_name: Callable[[Any], str],
    get_active_strategy_params: Callable[[], dict],
    set_active_strategy_params: Callable[[dict], None],
    send_parameter_tuning_update: Callable[..., None],
    parameter_change_explainer: Callable[[str, str, Any, Any], str],
) -> dict:
    """Run parameter optimization for the active strategy."""

    if not settings.enable_auto_parameter_tuning:
        return {"applied": False, "summary": "파라미터 자동 조정 비활성"}

    if strategy_name not in param_ranges:
        return {
            "applied": False,
            "summary": f"{strategy_name} 전략은 자동 파라미터 조정 대상이 아닙니다",
        }

    latest = repo.get_latest_parameter_adjustment(strategy_name)
    if latest and settings.parameter_tuning_cooldown_hours > 0:
        applied_at = datetime.fromisoformat(latest["applied_at"])
        hours_since = (datetime.now() - applied_at).total_seconds() / 3600
        if hours_since < settings.parameter_tuning_cooldown_hours:
            return {
                "applied": False,
                "summary": (
                    f"{strategy_name} 파라미터 조정 쿨다운 중 "
                    f"({hours_since:.1f}/{settings.parameter_tuning_cooldown_hours}시간)"
                ),
            }

    optimizer = ParameterOptimizer(
        initial_balance=settings.paper_initial_balance,
        order_amount=settings.max_order_amount_krw,
        n_folds=settings.parameter_tuning_n_folds,
        min_wf_consistency=settings.parameter_tuning_min_wf_consistency,
        slippage_pct=settings.backtest_slippage_pct,
        spread_pct=settings.backtest_spread_pct,
        candle_interval=settings.candle_interval,
    )

    current_strategy = build_strategy_instance(settings, strategy_name)
    current_params = current_strategy.get_tunable_params()
    baseline = optimizer.evaluate_params(strategy_name, current_params, candles)
    result = optimizer.optimize(strategy_name, candles, n_trials=settings.optimizer_trials)

    if result.valid_trials == 0 or not result.best_params:
        return {
            "applied": False,
            "summary": f"{strategy_name} 파라미터 조정 후보 없음",
        }

    baseline_sharpe = baseline.get("sharpe", 0.0) if baseline else 0.0
    improvement = result.best_sharpe - baseline_sharpe
    metric_summary = (
        f"Sharpe {baseline_sharpe:.3f} -> {result.best_sharpe:.3f}, "
        f"WF 일관성 {result.best_wf_consistency:.0f}%, "
        f"수익 {result.best_return_pct:+.2f}%"
    )

    if improvement < settings.parameter_min_sharpe_improvement:
        return {
            "applied": False,
            "summary": (
                f"{strategy_name} 파라미터 유지 "
                f"(개선폭 {improvement:.3f} < 기준 {settings.parameter_min_sharpe_improvement:.3f})"
            ),
            "metric_summary": metric_summary,
        }

    explanations = {
        key: parameter_change_explainer(strategy_name, key, current_params.get(key), value)
        for key, value in result.best_params.items()
        if current_params.get(key) != value
    }
    changed = repo.apply_parameter_adjustments(
        strategy=strategy_name,
        new_params=result.best_params,
        reason=(
            f"최근 {settings.arena_lookback_days}개 캔들 기준 "
            "Walk-Forward 통과 후보 중 Sharpe 개선"
        ),
        metric_summary=metric_summary,
        explanations=explanations,
        previous_params=current_params,
    )

    if not changed:
        return {
            "applied": False,
            "summary": f"{strategy_name} 파라미터 유지 (현재 값과 최적값 동일)",
            "metric_summary": metric_summary,
        }

    if strategy_name == get_effective_strategy_name(settings):
        set_active_strategy_params(repo.get_strategy_parameters(strategy_name))

    logger.info("파라미터 자동 조정 적용: %s %s", strategy_name, changed)
    if bot:
        send_parameter_tuning_update(bot, strategy_name, changed, metric_summary)

    return {
        "applied": True,
        "summary": f"{strategy_name} 파라미터 자동 조정 적용",
        "metric_summary": metric_summary,
        "changed": changed,
    }


def parameter_tuning_job(
    client,
    repo,
    bot,
    symbols: list[str],
    settings,
    *,
    logger: logging.Logger,
    get_effective_strategy_name: Callable[[Any], str],
    build_strategy_instance: Callable[..., Any],
    run_parameter_tuning: Callable[..., dict],
) -> None:
    """Periodically optimize the active strategy parameters."""

    if not settings.enable_auto_parameter_tuning:
        return

    try:
        strategy_name = get_effective_strategy_name(settings)
        strategy = build_strategy_instance(settings, strategy_name)
        candle_count = max(
            settings.parameter_tuning_lookback_candles,
            strategy.required_candle_count() * 3,
        )

        tune_symbols = symbols if symbols else settings.symbol_list
        if not tune_symbols:
            tune_symbols = ["KRW-BTC"]

        all_candles: list[list] = []
        for sym in tune_symbols:
            try:
                sym_candles = client.get_candles(
                    sym,
                    interval=settings.candle_interval,
                    count=candle_count,
                )
                if len(sym_candles) >= strategy.required_candle_count():
                    all_candles.append(sym_candles)
            except Exception:
                logger.warning("파라미터 튜닝 캔들 조회 실패: %s", sym)

        if not all_candles:
            logger.warning("파라미터 튜닝: 유효 캔들 없음")
            return

        result = run_parameter_tuning(
            repo=repo,
            settings=settings,
            strategy_name=strategy_name,
            candles=all_candles[0],
            bot=bot,
        )
        logger.info("파라미터 조정 job 완료: %s", result["summary"])
    except Exception:
        logger.exception("파라미터 조정 job 실패")
