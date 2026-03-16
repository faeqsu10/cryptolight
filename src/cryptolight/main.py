"""cryptolight 진입점 - 전략 실행, 시그널 알림, paper/live trading, 리스크 관리"""

import argparse
import logging
import threading

from apscheduler.schedulers.blocking import BlockingScheduler

from cryptolight.bot.command_handler import CommandHandler
from cryptolight.bot.telegram_bot import TelegramBot
from cryptolight.config import get_settings
from cryptolight.exchange.candle_cache import CandleCache
from cryptolight.health import HealthMonitor
from cryptolight.market.price_stream import PriceStream
from cryptolight.market.regime import MarketRegime
from cryptolight.strategy.volume_filter import VolumeFilter
from cryptolight.exchange.upbit import UpbitClient
from cryptolight.execution.base import BaseBroker
from cryptolight.execution.live_broker import LiveBroker
from cryptolight.execution.paper_broker import PaperBroker
from cryptolight.risk.cooldown import TradeCooldown
from cryptolight.risk.position_sizer import PositionSizer
from cryptolight.risk.risk_guard import RiskGuard
from cryptolight.storage.repository import TradeRepository

from cryptolight.bot.ai_assistant import AIAssistant, markdown_to_telegram_html
from cryptolight.bot.formatters import (
    explain_indicators,
    parameter_change_explainer,
)
from cryptolight.evaluation import (
    PerformanceEvaluator,
    StrategyArena,
    AdaptiveController,
    ParameterOptimizer,
)
from cryptolight.evaluation.optimizer import PARAM_RANGES
from cryptolight.runtime.bootstrap import (
    bootstrap_runtime as runtime_bootstrap_runtime,
)
from cryptolight.runtime.commanding import command_loop as runtime_command_loop
from cryptolight.runtime.improvement import (
    parameter_tuning_job as runtime_parameter_tuning_job,
    run_parameter_tuning as runtime_run_parameter_tuning,
    self_improvement_job as runtime_self_improvement_job,
)
from cryptolight.runtime.orchestrator import (
    daily_summary_job as runtime_daily_summary_job,
    start_scheduler_runtime as runtime_start_scheduler_runtime,
    setup_runtime_services as runtime_setup_runtime_services,
)
from cryptolight.runtime.reporting import (
    build_market_context as runtime_build_market_context,
    build_strategy_criteria_lines as runtime_build_strategy_criteria_lines,
    build_tuning_history_lines as runtime_build_tuning_history_lines,
    send_market_info as runtime_send_market_info,
    send_parameter_tuning_update as runtime_send_parameter_tuning_update,
    send_strategy_criteria as runtime_send_strategy_criteria,
    send_tuning_history as runtime_send_tuning_history,
)
from cryptolight.runtime.state import (
    active_symbols as _active_symbols,
    get_market_snapshots_copy as _get_market_snapshots_copy,
    get_runtime_state as runtime_get_runtime_state,
    market_snapshots as _market_snapshots,
    set_active_symbols as _set_active_symbols,
    update_market_snapshot as _update_market_snapshot,
)
from cryptolight.runtime.strategy_engine import (
    make_ws_price_callback as runtime_make_ws_price_callback,
    price_monitor_job as runtime_price_monitor_job,
    run_strategy as runtime_run_strategy,
    strategy_job as runtime_strategy_job,
)
from cryptolight.strategy import create_strategy
from cryptolight.strategy.score_based import REGIME_WEIGHTS
from cryptolight.utils import setup_logger

logger = logging.getLogger("cryptolight.main")

# 중복 시그널 방지: symbol -> action (스레드 안전)
_last_signals: dict[str, str] = {}
_signal_lock = threading.Lock()
# 모듈 레벨 캐시/쿨다운 (main()에서 초기화)
_candle_cache: CandleCache | None = None
_cooldown: TradeCooldown | None = None
_position_sizer: PositionSizer | None = None
_health: HealthMonitor | None = None
_regime_detector: MarketRegime | None = None
_volume_filter: VolumeFilter | None = None
_ai_assistant: AIAssistant | None = None
_cmd_handler: CommandHandler | None = None
_scheduler: BlockingScheduler | None = None
_price_stream: PriceStream | None = None
_active_strategy_name: str = ""  # HIGH-1: mutable 전략명 (자기개선 루프에서 전환)
_active_strategy_params: dict = {}  # 자동 조정된 활성 전략 파라미터


def _get_effective_strategy_name(settings) -> str:
    return _active_strategy_name or settings.strategy_name


def _get_effective_strategy_params(settings, strategy_name: str | None = None) -> dict:
    name = strategy_name or _get_effective_strategy_name(settings)
    if name == _get_effective_strategy_name(settings):
        return dict(_active_strategy_params)
    return {}


def _build_strategy_instance(settings, strategy_name: str | None = None, params: dict | None = None):
    name = strategy_name or _get_effective_strategy_name(settings)
    strategy_params = dict(params) if params is not None else _get_effective_strategy_params(settings, name)
    if name == "ensemble":
        return create_strategy("ensemble", strategy_names=settings.ensemble_strategy_list)
    return create_strategy(name, **strategy_params)



def _load_active_strategy_parameters(repo: TradeRepository, settings, logger=None) -> dict:
    strategy_name = _get_effective_strategy_name(settings)
    params = repo.get_strategy_parameters(strategy_name)
    global _active_strategy_params
    _active_strategy_params = params
    if logger and params:
        logger.info("적용된 자동 조정 파라미터: %s", params)
    return params


def _set_active_strategy_name(strategy_name: str) -> None:
    global _active_strategy_name
    _active_strategy_name = strategy_name


def _set_active_strategy_params(params: dict) -> None:
    global _active_strategy_params
    _active_strategy_params = dict(params)


def _get_runtime_state(settings) -> dict:
    return runtime_get_runtime_state(
        settings,
        get_effective_strategy_name=_get_effective_strategy_name,
    )


def _apply_runtime_session(session) -> tuple:
    bot = session.bot
    cmd_handler = session.cmd_handler
    repo = session.repo
    risk_guard = session.risk_guard
    client = session.client
    broker = session.broker
    symbols = session.symbols

    global _cmd_handler
    _cmd_handler = cmd_handler

    global _candle_cache, _cooldown, _position_sizer, _health, _regime_detector, _volume_filter, _ai_assistant
    runtime_components = session.components
    _health = runtime_components.health
    _regime_detector = runtime_components.regime_detector
    _volume_filter = runtime_components.volume_filter
    _ai_assistant = runtime_components.ai_assistant
    _candle_cache = runtime_components.candle_cache
    _cooldown = runtime_components.cooldown
    _position_sizer = runtime_components.position_sizer

    _set_active_symbols(list(symbols))

    return bot, cmd_handler, repo, risk_guard, client, broker, symbols


def run_strategy(
    client: UpbitClient,
    bot: TelegramBot | None,
    broker: BaseBroker | None,
    risk_guard: RiskGuard | None,
    symbols: list[str],
    settings,
):
    runtime_run_strategy(
        client,
        bot,
        broker,
        risk_guard,
        symbols,
        settings,
        logger=logger,
        get_effective_strategy_name=_get_effective_strategy_name,
        build_strategy_instance=_build_strategy_instance,
        candle_cache=_candle_cache,
        update_market_snapshot=_update_market_snapshot,
        cmd_handler=_cmd_handler,
        regime_detector=_regime_detector,
        volume_filter=_volume_filter,
        signal_lock=_signal_lock,
        last_signals=_last_signals,
        cooldown=_cooldown,
        position_sizer=_position_sizer,
        market_snapshots=_market_snapshots,
        explain_indicators=explain_indicators,
    )


def strategy_job(
    client: UpbitClient,
    bot: TelegramBot | None,
    broker: BaseBroker | None,
    risk_guard: RiskGuard | None,
    symbols: list[str],
    settings,
):
    runtime_strategy_job(
        client,
        bot,
        broker,
        risk_guard,
        symbols,
        settings,
        logger=logger,
        health=_health,
        run_strategy_fn=run_strategy,
    )


def price_monitor_job(
    client: UpbitClient,
    bot: TelegramBot | None,
    broker: BaseBroker | None,
    risk_guard: RiskGuard | None,
    symbols: list[str],
):
    runtime_price_monitor_job(
        client,
        bot,
        broker,
        risk_guard,
        symbols,
        logger=logger,
        update_market_snapshot=_update_market_snapshot,
    )


def _make_ws_price_callback(
    broker: BaseBroker,
    risk_guard: RiskGuard,
    bot: TelegramBot | None,
):
    return runtime_make_ws_price_callback(
        broker,
        risk_guard,
        bot,
        logger=logger,
        update_market_snapshot=_update_market_snapshot,
    )


def daily_summary_job(
    bot: TelegramBot,
    broker: BaseBroker | None,
    repo: TradeRepository,
    client: UpbitClient,
    symbols: list[str],
):
    runtime_daily_summary_job(
        bot,
        broker,
        repo,
        client,
        symbols,
        logger=logger,
    )


def self_improvement_job(
    client: UpbitClient,
    repo: TradeRepository,
    bot: TelegramBot | None,
    settings,
):
    runtime_self_improvement_job(
        client,
        repo,
        bot,
        settings,
        logger=logger,
        get_effective_strategy_name=_get_effective_strategy_name,
        load_active_strategy_parameters=_load_active_strategy_parameters,
        set_active_strategy_name=_set_active_strategy_name,
    )


def _build_market_context() -> str:
    return runtime_build_market_context(
        get_market_snapshots_copy=_get_market_snapshots_copy,
    )


def _send_market_info(bot: TelegramBot, settings) -> None:
    runtime_send_market_info(
        bot,
        settings,
        get_market_snapshots_copy=_get_market_snapshots_copy,
        get_effective_strategy_name=_get_effective_strategy_name,
        build_strategy_criteria_lines=_build_strategy_criteria_lines,
    )


def _build_strategy_criteria_lines(settings) -> list[str]:
    return runtime_build_strategy_criteria_lines(
        settings,
        build_strategy_instance=_build_strategy_instance,
        get_effective_strategy_name=_get_effective_strategy_name,
        get_effective_strategy_params=_get_effective_strategy_params,
        get_market_snapshots_copy=_get_market_snapshots_copy,
        regime_weights=REGIME_WEIGHTS,
    )


def _send_strategy_criteria(bot: TelegramBot, settings) -> None:
    runtime_send_strategy_criteria(
        bot,
        settings,
        build_strategy_criteria_lines=_build_strategy_criteria_lines,
    )


def _build_tuning_history_lines(repo: TradeRepository, settings) -> list[str]:
    return runtime_build_tuning_history_lines(
        repo,
        settings,
        get_effective_strategy_name=_get_effective_strategy_name,
        build_strategy_instance=_build_strategy_instance,
        scheduler=_scheduler,
    )


def _send_tuning_history(bot: TelegramBot, repo: TradeRepository, settings) -> None:
    runtime_send_tuning_history(
        bot,
        repo,
        settings,
        build_tuning_history_lines=_build_tuning_history_lines,
    )


def _send_parameter_tuning_update(
    bot: TelegramBot,
    strategy_name: str,
    changed: list[dict],
    metric_summary: str,
) -> None:
    runtime_send_parameter_tuning_update(
        bot,
        strategy_name,
        changed,
        metric_summary,
    )


def _run_parameter_tuning(
    repo: TradeRepository,
    settings,
    strategy_name: str,
    candles,
    bot: TelegramBot | None = None,
) -> dict:
    return runtime_run_parameter_tuning(
        repo,
        settings,
        strategy_name,
        candles,
        logger=logger,
        param_ranges=PARAM_RANGES,
        bot=bot,
        build_strategy_instance=_build_strategy_instance,
        get_effective_strategy_name=_get_effective_strategy_name,
        get_active_strategy_params=lambda: dict(_active_strategy_params),
        set_active_strategy_params=_set_active_strategy_params,
        send_parameter_tuning_update=_send_parameter_tuning_update,
        parameter_change_explainer=parameter_change_explainer,
    )


def parameter_tuning_job(
    client: UpbitClient,
    repo: TradeRepository,
    bot: TelegramBot | None,
    symbols: list[str],
    settings,
):
    runtime_parameter_tuning_job(
        client,
        repo,
        bot,
        symbols,
        settings,
        logger=logger,
        get_effective_strategy_name=_get_effective_strategy_name,
        build_strategy_instance=_build_strategy_instance,
        run_parameter_tuning=_run_parameter_tuning,
    )


def command_loop(
    cmd_handler: CommandHandler,
    scheduler: BlockingScheduler,
    bot: TelegramBot | None,
    broker: BaseBroker | None = None,
    repo: TradeRepository | None = None,
    client: UpbitClient | None = None,
    symbols: list[str] | None = None,
    settings=None,
    stop_event: threading.Event | None = None,
):
    runtime_command_loop(
        cmd_handler,
        scheduler,
        bot,
        logger=logger,
        broker=broker,
        repo=repo,
        client=client,
        symbols=symbols,
        settings=settings,
        stop_event=stop_event,
        daily_summary_job=daily_summary_job,
        health=_health,
        get_runtime_state=_get_runtime_state,
        send_market_info=_send_market_info,
        send_strategy_criteria=_send_strategy_criteria,
        send_tuning_history=_send_tuning_history,
        ai_assistant=_ai_assistant,
        build_market_context=_build_market_context,
        markdown_to_telegram_html=markdown_to_telegram_html,
    )


def main():
    parser = argparse.ArgumentParser(description="cryptolight trading bot")
    parser.add_argument("--once", action="store_true", help="1회 실행 후 종료")
    args = parser.parse_args()

    settings = get_settings()
    setup_logger("cryptolight", settings.log_level, settings.log_file)

    once_mode = args.once or settings.schedule_interval_minutes == 0

    logger.info("cryptolight v0.1.0 시작")
    logger.info("거래 모드: %s", settings.trade_mode)
    logger.info("대상 종목: %s", settings.symbol_list)

    session = runtime_bootstrap_runtime(
        settings,
        logger=logger,
        load_active_strategy_parameters=_load_active_strategy_parameters,
    )
    if session is None:
        return

    bot, cmd_handler, repo, risk_guard, client, broker, symbols = _apply_runtime_session(session)

    if bot:
        bot.send_startup(_active_symbols, settings.trade_mode)

    # ── 1회 실행 모드 ──
    if once_mode:
        logger.info("1회 실행 모드")
        try:
            run_strategy(client, bot, broker, risk_guard, symbols, settings)
        finally:
            if _ai_assistant:
                _ai_assistant.close()
            if bot:
                bot.close()
            if cmd_handler:
                cmd_handler.close()
            client.close()
            repo.close()
        logger.info("cryptolight 종료")
        return

    global _scheduler
    global _price_stream
    services = runtime_setup_runtime_services(
        settings,
        logger=logger,
        client=client,
        bot=bot,
        broker=broker,
        risk_guard=risk_guard,
        symbols=symbols,
        cmd_handler=cmd_handler,
        repo=repo,
        health=_health,
        market_snapshots=_market_snapshots,
        get_market_snapshots_copy=_get_market_snapshots_copy,
        get_runtime_state=_get_runtime_state,
        strategy_job=strategy_job,
        price_monitor_job=price_monitor_job,
        make_ws_price_callback=_make_ws_price_callback,
        command_loop=command_loop,
        daily_summary_job=daily_summary_job,
        self_improvement_job=self_improvement_job,
        parameter_tuning_job=parameter_tuning_job,
    )
    _scheduler = services.scheduler
    _price_stream = services.price_stream

    try:
        runtime_start_scheduler_runtime(
            services,
            settings,
            logger=logger,
            strategy_job=strategy_job,
            client=client,
            bot=bot,
            broker=broker,
            risk_guard=risk_guard,
            symbols=symbols,
        )
    finally:
        logger.info("스케줄러 종료 — 리소스 정리")
        _scheduler = None
        if _price_stream:
            _price_stream.stop()
        if _ai_assistant:
            _ai_assistant.close()
        if bot:
            bot.send_message("\U0001f6d1 cryptolight 종료됩니다.")
            bot.close()
        if cmd_handler:
            cmd_handler.close()
        client.close()
        repo.close()

    logger.info("cryptolight 종료")


if __name__ == "__main__":
    main()
