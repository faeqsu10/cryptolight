"""Bootstrap helpers extracted from the main runtime entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
import html as html_mod
import logging
from pathlib import Path

from cryptolight.bot.ai_assistant import AIAssistant
from cryptolight.bot.command_handler import CommandHandler
from cryptolight.bot.telegram_bot import TelegramBot
from cryptolight.exchange.candle_cache import CandleCache
from cryptolight.exchange.upbit import UpbitClient
from cryptolight.execution.live_broker import LiveBroker
from cryptolight.execution.paper_broker import PaperBroker
from cryptolight.health import HealthMonitor
from cryptolight.market.regime import MarketRegime
from cryptolight.market.screener import run_screening_pipeline
from cryptolight.risk.cooldown import TradeCooldown
from cryptolight.risk.position_sizer import PositionSizer
from cryptolight.risk.risk_guard import RiskGuard
from cryptolight.storage.repository import TradeRepository
from cryptolight.strategy.volume_filter import VolumeFilter


@dataclass
class RuntimeComponents:
    health: HealthMonitor
    regime_detector: MarketRegime
    volume_filter: VolumeFilter
    ai_assistant: AIAssistant | None
    candle_cache: CandleCache
    cooldown: TradeCooldown
    position_sizer: PositionSizer


@dataclass
class RuntimeSession:
    bot: TelegramBot | None
    cmd_handler: CommandHandler | None
    repo: TradeRepository
    risk_guard: RiskGuard
    client: UpbitClient
    components: RuntimeComponents
    broker: PaperBroker | LiveBroker | None
    symbols: list[str]


def initialize_telegram(settings, *, logger: logging.Logger):
    bot = None
    cmd_handler = None
    if settings.telegram_bot_token and settings.telegram_chat_id:
        bot = TelegramBot(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            notification_level=settings.notification_level,
        )
        cmd_handler = CommandHandler(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            poll_timeout_seconds=settings.telegram_poll_timeout_seconds,
            request_timeout_seconds=settings.telegram_request_timeout_seconds,
        )
        logger.info("텔레그램 봇 연결됨")
    else:
        logger.warning("텔레그램 설정 없음 — 알림 비활성화")
    return bot, cmd_handler


def handle_initial_killswitch(cmd_handler, bot, *, logger: logging.Logger) -> bool:
    if not cmd_handler:
        return False
    cmd_handler.poll_commands()
    if cmd_handler.kill_switch:
        logger.warning("킬스위치 활성 — 실행 중단")
        if bot:
            bot.close()
        cmd_handler.close()
        return True
    return False


def initialize_storage_and_clients(settings, *, logger: logging.Logger, load_active_strategy_parameters):
    repo = TradeRepository(db_path=Path(settings.db_path))
    load_active_strategy_parameters(repo, settings, logger)
    risk_guard = RiskGuard(
        max_order_amount_krw=settings.max_order_amount_krw,
        daily_loss_limit_krw=settings.daily_loss_limit_krw,
        max_positions=settings.max_positions,
        stop_loss_pct=settings.stop_loss_pct,
        take_profit_pct=settings.take_profit_pct,
        trailing_stop_pct=settings.trailing_stop_pct,
        repo=repo,
        commission_rate=settings.commission_rate,
    )
    client = UpbitClient(settings.upbit_access_key, settings.upbit_secret_key)
    return repo, risk_guard, client


def initialize_runtime_components(settings, *, logger: logging.Logger) -> RuntimeComponents:
    health = HealthMonitor()
    regime_detector = MarketRegime()
    volume_filter = VolumeFilter()
    ai_assistant = None
    if settings.google_api_key:
        ai_assistant = AIAssistant(
            api_key=settings.google_api_key,
            model=settings.gemini_model,
            daily_limit=settings.ask_daily_limit,
        )
        logger.info(
            "AI 어시스턴트 활성화 (모델: %s, 일일 %d회 제한)",
            settings.gemini_model,
            settings.ask_daily_limit,
        )

    candle_cache = CandleCache(ttl_seconds=settings.candle_cache_ttl)
    cooldown = TradeCooldown(
        cooldown_seconds=settings.trade_cooldown_seconds,
        max_orders_per_hour=settings.max_orders_per_hour,
    )
    position_sizer = PositionSizer(
        method=settings.position_sizing_method,
        fixed_amount=settings.max_order_amount_krw,
        risk_pct=settings.position_risk_pct,
        max_amount=settings.absolute_max_order_krw,
    )
    logger.info(
        "포지션 사이징: %s, 쿨다운: %ds, 캔들캐시 TTL: %ds",
        settings.position_sizing_method,
        settings.trade_cooldown_seconds,
        settings.candle_cache_ttl,
    )
    return RuntimeComponents(
        health=health,
        regime_detector=regime_detector,
        volume_filter=volume_filter,
        ai_assistant=ai_assistant,
        candle_cache=candle_cache,
        cooldown=cooldown,
        position_sizer=position_sizer,
    )


def initialize_broker(settings, client, repo, bot, *, logger: logging.Logger):
    broker = None
    if settings.trade_mode == "paper":
        broker = PaperBroker(
            initial_balance=settings.paper_initial_balance,
            repo=repo,
            commission_rate=settings.commission_rate,
        )
        logger.info("Paper trading 초기화: 초기 자금 %s KRW", f"{broker.initial_balance:,.0f}")
    elif settings.trade_mode == "live":
        broker = LiveBroker(
            client=client,
            repo=repo,
            absolute_max_order_krw=settings.absolute_max_order_krw,
            commission_rate=settings.commission_rate,
        )
        logger.info("Live trading 초기화 (하드캡: %s KRW)", f"{settings.absolute_max_order_krw:,.0f}")
        if bot:
            bot.send_message("\u26a0\ufe0f <b>LIVE 모드</b>로 실행 중입니다.")

    logger.info(
        "리스크 설정: 최대주문 %s, 일일손실한도 %s, 손절 %s%%, 익절 %s%%",
        f"{settings.max_order_amount_krw:,.0f}",
        f"{settings.daily_loss_limit_krw:,.0f}",
        settings.stop_loss_pct,
        settings.take_profit_pct,
    )
    return broker


def select_symbols(settings, client, broker, bot, *, logger: logging.Logger) -> list[str]:
    symbols = settings.symbol_list
    if settings.auto_select_symbols:
        logger.info(
            "자동 종목 스크리닝 시작 (상위 %d개, 최소 거래대금 %s원)",
            settings.top_volume_limit,
            f"{settings.min_daily_volume_krw:,}",
        )
        try:
            screening = run_screening_pipeline(
                client=client,
                strategy_name=settings.strategy_name,
                top_limit=settings.top_volume_limit,
                min_volume_krw=settings.min_daily_volume_krw,
                min_sharpe=settings.min_backtest_sharpe,
                max_correlation=settings.max_correlation,
                max_positions=settings.max_positions,
                candle_interval=settings.candle_interval,
            )
            if screening.selected:
                symbols = screening.selected
                logger.info("자동 스크리닝 결과: %s", symbols)
                if bot:
                    details_lines = []
                    for sym in screening.selected:
                        detail = screening.backtest_details.get(sym, {})
                        if detail and not detail.get("skipped"):
                            details_lines.append(
                                f"  {sym}: Sharpe={detail['sharpe']:.4f}, "
                                f"수익={detail['return_pct']:+.2f}%, "
                                f"거래={detail['total_trades']}회"
                            )
                        else:
                            details_lines.append(f"  {sym}: 백테스트 데이터 없음")
                    msg = (
                        f"후보: {len(screening.candidates)}개\n"
                        f"백테스트 통과: {len(screening.backtest_passed)}개\n"
                        f"상관관계 제외: {screening.correlation_removed}\n"
                        f"최종 선정:\n" + "\n".join(details_lines)
                    )
                    bot.send_message(f"\U0001f50d <b>자동 종목 스크리닝</b>\n<pre>{html_mod.escape(msg)}</pre>")
            else:
                logger.warning("자동 스크리닝 결과 없음 — 기본 종목 사용: %s", settings.symbol_list)
        except Exception:
            logger.exception("자동 스크리닝 실패 — 기본 종목 사용")

    if broker:
        for pos_sym, pos in broker.get_positions().items():
            if pos.quantity > 0 and pos_sym not in symbols:
                symbols.append(pos_sym)
                logger.info("보유 종목 자동 추가: %s (스크리닝 대상 외)", pos_sym)

    return symbols


def bootstrap_runtime(
    settings,
    *,
    logger: logging.Logger,
    load_active_strategy_parameters,
) -> RuntimeSession | None:
    bot, cmd_handler = initialize_telegram(settings, logger=logger)
    if handle_initial_killswitch(cmd_handler, bot, logger=logger):
        return None

    repo, risk_guard, client = initialize_storage_and_clients(
        settings,
        logger=logger,
        load_active_strategy_parameters=load_active_strategy_parameters,
    )
    components = initialize_runtime_components(settings, logger=logger)
    broker = initialize_broker(settings, client, repo, bot, logger=logger)
    symbols = select_symbols(settings, client, broker, bot, logger=logger)

    return RuntimeSession(
        bot=bot,
        cmd_handler=cmd_handler,
        repo=repo,
        risk_guard=risk_guard,
        client=client,
        components=components,
        broker=broker,
        symbols=symbols,
    )
