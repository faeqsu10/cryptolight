"""Scheduler and runtime service orchestration extracted from main."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import signal
import threading

from apscheduler.schedulers.blocking import BlockingScheduler

from cryptolight.market.price_stream import PriceStream
from cryptolight.storage.strategy_tracker import StrategyTracker


@dataclass
class RuntimeServices:
    scheduler: BlockingScheduler
    price_stream: PriceStream | None
    cmd_stop_event: threading.Event


def daily_summary_job(
    bot,
    broker,
    repo,
    client,
    symbols: list[str],
    *,
    logger: logging.Logger,
) -> None:
    """Send the daily Telegram summary."""
    try:
        pnl_data = repo.get_daily_pnl()
        positions_summary = ""
        prices: dict[str, float] = {}

        if broker is not None:
            for symbol in symbols:
                ticker = client.get_ticker(symbol)
                prices[symbol] = ticker.price

            for pos_symbol, pos in broker.get_positions().items():
                if pos.quantity > 0 and pos_symbol not in prices:
                    try:
                        pos_ticker = client.get_ticker(pos_symbol)
                        prices[pos_symbol] = pos_ticker.price
                    except Exception:
                        pass
            positions_summary = broker.summary_text(prices)

        today_str = datetime.now().strftime("%Y-%m-%d")
        today_trades = repo.get_trades_by_date(today_str)
        tracker = StrategyTracker(repo)
        strategy_summary = tracker.summary_text()

        holdings = []
        if broker is not None:
            for pos_sym, pos in broker.get_positions().items():
                if pos.quantity > 0:
                    cur_price = prices.get(pos_sym, 0)
                    holdings.append({
                        "symbol": pos_sym,
                        "coin": pos_sym.split("-")[1] if "-" in pos_sym else pos_sym,
                        "quantity": pos.quantity,
                        "avg_price": pos.avg_price,
                        "current_price": cur_price,
                        "eval_amount": pos.quantity * cur_price,
                        "cost": pos.quantity * pos.avg_price,
                        "pnl": (cur_price - pos.avg_price) * pos.quantity,
                    })

        bot.send_daily_summary(
            pnl_data,
            positions_summary,
            today_trades,
            holdings,
            broker.get_balance_krw() if broker else 0,
        )
        if strategy_summary and "데이터 없음" not in strategy_summary:
            bot.send_message(f"<b>전략별 성과</b>\n<pre>{strategy_summary}</pre>")
        logger.info("일일 요약 전송 완료")
    except Exception:
        logger.exception("일일 요약 전송 실패")


def _make_ws_hooks(scheduler: BlockingScheduler, *, logger: logging.Logger):
    def on_connect():
        try:
            scheduler.pause_job("price_monitor")
            logger.info("WebSocket 연결됨 — price_monitor 폴링 일시 정지")
        except Exception:
            pass

    def on_disconnect():
        try:
            scheduler.resume_job("price_monitor")
            logger.warning("WebSocket 끊김 — price_monitor 폴링 재개")
        except Exception:
            pass

    return on_connect, on_disconnect


def start_web_dashboard(
    settings,
    *,
    market_snapshots,
    get_market_snapshots_copy,
    broker,
    repo,
    health,
    get_runtime_state,
    logger: logging.Logger,
) -> None:
    if not settings.enable_web:
        return

    try:
        import uvicorn
        from cryptolight.web.app import app as web_app, configure as web_configure

        web_configure(
            market_snapshots=market_snapshots,
            market_snapshot_getter=get_market_snapshots_copy,
            broker=broker,
            repo=repo,
            health=health,
            settings=settings,
            runtime_state_getter=lambda: get_runtime_state(settings),
        )
        web_thread = threading.Thread(
            target=uvicorn.run,
            kwargs={"app": web_app, "host": settings.web_host, "port": settings.web_port, "log_level": "warning"},
            daemon=True,
            name="web-dashboard",
        )
        web_thread.start()
        logger.info("웹 대시보드 시작: http://%s:%d", settings.web_host, settings.web_port)
    except ImportError:
        logger.warning("웹 대시보드 비활성: fastapi/uvicorn 미설치 (pip install cryptolight[web])")


def setup_runtime_services(
    settings,
    *,
    logger: logging.Logger,
    client,
    bot,
    broker,
    risk_guard,
    symbols: list[str],
    cmd_handler,
    repo,
    health,
    market_snapshots,
    get_market_snapshots_copy,
    get_runtime_state,
    strategy_job,
    price_monitor_job,
    make_ws_price_callback,
    command_loop,
    daily_summary_job,
    self_improvement_job,
    parameter_tuning_job,
) -> RuntimeServices:
    logger.info(
        "스케줄러 모드: 전략 분석 %d분 / 가격 모니터링 %d분",
        settings.schedule_interval_minutes,
        settings.price_monitor_interval_minutes,
    )
    scheduler = BlockingScheduler(timezone=settings.app_timezone)
    scheduler.add_job(
        strategy_job,
        "interval",
        minutes=settings.schedule_interval_minutes,
        max_instances=1,
        misfire_grace_time=300,
        args=[client, bot, broker, risk_guard, symbols, settings],
        id="strategy",
        next_run_time=None,
    )

    if broker and risk_guard and settings.price_monitor_interval_minutes > 0:
        scheduler.add_job(
            price_monitor_job,
            "interval",
            minutes=settings.price_monitor_interval_minutes,
            max_instances=1,
            misfire_grace_time=30,
            args=[client, bot, broker, risk_guard, symbols],
            id="price_monitor",
        )
        logger.info("가격 모니터링: %d분 간격 (손절/익절 체크)", settings.price_monitor_interval_minutes)

    price_stream = None
    if broker and risk_guard and settings.enable_websocket:
        on_connect, on_disconnect = _make_ws_hooks(scheduler, logger=logger)
        ws_callback = make_ws_price_callback(broker, risk_guard, bot)
        price_stream = PriceStream(
            symbols=symbols,
            on_price_callback=ws_callback,
            on_connect=on_connect,
            on_disconnect=on_disconnect,
            reconnect_max_seconds=settings.websocket_reconnect_max_seconds,
        )
        price_stream.start()
        logger.info("WebSocket 실시간 가격 스트림 활성화 (fallback: %d분 폴링)", settings.price_monitor_interval_minutes)

    cmd_stop_event = threading.Event()
    if cmd_handler:
        cmd_thread = threading.Thread(
            target=command_loop,
            args=[cmd_handler, scheduler, bot, broker, repo, client, symbols, settings, cmd_stop_event],
            daemon=True,
            name="command-poll",
        )
        cmd_thread.start()

    if bot:
        scheduler.add_job(
            daily_summary_job,
            "cron",
            hour=settings.daily_summary_hour,
            minute=settings.daily_summary_minute,
            args=[bot, broker, repo, client, symbols],
            id="daily_summary",
        )

    if settings.enable_auto_optimization:
        scheduler.add_job(
            self_improvement_job,
            "cron",
            day_of_week=settings.self_improvement_day_of_week,
            hour=settings.self_improvement_hour,
            minute=settings.self_improvement_minute,
            args=[client, repo, bot, settings],
            id="self_improvement",
        )
        logger.info(
            "전략 전환 루프 활성화: %s %02d:%02d 실행 (%s)",
            settings.self_improvement_day_of_week,
            settings.self_improvement_hour,
            settings.self_improvement_minute,
            settings.app_timezone,
        )

    if settings.enable_auto_parameter_tuning and settings.parameter_tuning_interval_hours > 0:
        scheduler.add_job(
            parameter_tuning_job,
            "interval",
            hours=settings.parameter_tuning_interval_hours,
            max_instances=1,
            misfire_grace_time=300,
            args=[client, repo, bot, symbols, settings],
            id="parameter_tuning",
        )
        logger.info(
            "파라미터 조정 루프 활성화: %d시간마다 실행, 쿨다운 %d시간",
            settings.parameter_tuning_interval_hours,
            settings.parameter_tuning_cooldown_hours,
        )

    start_web_dashboard(
        settings,
        market_snapshots=market_snapshots,
        get_market_snapshots_copy=get_market_snapshots_copy,
        broker=broker,
        repo=repo,
        health=health,
        get_runtime_state=get_runtime_state,
        logger=logger,
    )

    return RuntimeServices(
        scheduler=scheduler,
        price_stream=price_stream,
        cmd_stop_event=cmd_stop_event,
    )


def start_scheduler_runtime(
    services: RuntimeServices,
    settings,
    *,
    logger: logging.Logger,
    strategy_job,
    client,
    bot,
    broker,
    risk_guard,
    symbols: list[str],
) -> None:
    """Start the scheduler after installing signal handlers and initial run."""

    def _shutdown(signum, _frame):
        sig_name = signal.Signals(signum).name
        logger.info("시그널 수신: %s — graceful shutdown", sig_name)
        services.scheduler.shutdown(wait=False)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    strategy_job(client, bot, broker, risk_guard, symbols, settings)
    services.scheduler.reschedule_job("strategy", trigger="interval", minutes=settings.schedule_interval_minutes)
    services.scheduler.start()
