"""cryptolight 진입점 - 전략 실행, 시그널 알림, paper/live trading, 리스크 관리"""

import argparse
import signal
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler

from cryptolight.bot.command_handler import CommandHandler
from cryptolight.bot.telegram_bot import TelegramBot
from cryptolight.config import get_settings
from cryptolight.exchange.upbit import UpbitClient
from cryptolight.execution.base import BaseBroker
from cryptolight.execution.live_broker import LiveBroker
from cryptolight.execution.paper_broker import PaperBroker
from cryptolight.risk.risk_guard import RiskGuard
from cryptolight.storage.repository import TradeRepository
from cryptolight.strategy.rsi import RSIStrategy
from cryptolight.utils import setup_logger

# 중복 시그널 방지: symbol -> action
_last_signals: dict[str, str] = {}


def run_strategy(
    client: UpbitClient,
    bot: TelegramBot | None,
    broker: BaseBroker | None,
    risk_guard: RiskGuard | None,
    symbols: list[str],
    settings,
):
    """각 종목에 대해 전략을 실행하고 시그널을 전송한다."""
    logger = setup_logger("cryptolight.main")
    strategy = RSIStrategy(period=14, oversold=30, overbought=70)

    for symbol in symbols:
        candles = client.get_candles(symbol, interval="day", count=strategy.required_candle_count() * 2)
        ticker = client.get_ticker(symbol)

        logger.info(
            "%s 현재가: %s KRW (변동: %+.2f%%)",
            symbol, f"{ticker.price:,.0f}", ticker.change_rate * 100,
        )

        # 손절/익절 체크 (paper 모드만 — live는 포지션을 broker가 관리하지 않음)
        if isinstance(broker, PaperBroker) and risk_guard:
            pos = broker.positions.get(symbol)
            if pos and pos.quantity > 0:
                sl_tp = risk_guard.check_stop_loss_take_profit(
                    symbol, pos.avg_price, pos.quantity, ticker.price,
                )
                if sl_tp == "stop_loss":
                    order = broker.sell_market(symbol, pos.quantity, ticker.price, reason="손절 트리거")
                    if order:
                        logger.warning("손절 매도 실행: %s %.8f @ %s", symbol, pos.quantity, f"{ticker.price:,.0f}")
                        if bot:
                            bot.send_message(f"\U0001f534 <b>손절 매도</b>\n{symbol} @ {ticker.price:,.0f} KRW")
                    continue
                elif sl_tp == "take_profit":
                    order = broker.sell_market(symbol, pos.quantity, ticker.price, reason="익절 트리거")
                    if order:
                        logger.info("익절 매도 실행: %s %.8f @ %s", symbol, pos.quantity, f"{ticker.price:,.0f}")
                        if bot:
                            bot.send_message(f"\U0001f7e2 <b>익절 매도</b>\n{symbol} @ {ticker.price:,.0f} KRW")
                    continue

        # 전략 분석
        signal_result = strategy.analyze(candles)
        signal_result.symbol = symbol

        logger.info(
            "[%s] %s — %s (신뢰도: %.0f%%, RSI: %s)",
            signal_result.action.upper(), symbol, signal_result.reason,
            signal_result.confidence * 100, signal_result.indicators.get("rsi", "N/A"),
        )

        # 중복 시그널 방지
        prev = _last_signals.get(symbol)
        if prev == signal_result.action:
            logger.info("중복 시그널 스킵: %s → %s", symbol, signal_result.action)
            continue
        _last_signals[symbol] = signal_result.action

        # 매수 실행
        if broker and signal_result.action == "buy":
            # 리스크 체크
            if risk_guard:
                if isinstance(broker, PaperBroker):
                    _balance_krw = broker.balance_krw
                    _active_positions = sum(
                        1 for p in broker.positions.values() if p.quantity > 0
                    )
                    _already_holding = (
                        symbol in broker.positions
                        and broker.positions[symbol].quantity > 0
                    )
                elif isinstance(broker, LiveBroker):
                    krw_bal = client.get_balance("KRW")
                    _balance_krw = krw_bal.available if krw_bal else 0.0
                    all_balances = client.get_balances()
                    _active_positions = sum(
                        1 for b in all_balances
                        if b.currency != "KRW" and b.available > 0
                    )
                    currency = symbol.split("-")[1]
                    coin_bal = client.get_balance(currency)
                    _already_holding = bool(coin_bal and coin_bal.available > 0)
                else:
                    _balance_krw = 0.0
                    _active_positions = 0
                    _already_holding = False

                check = risk_guard.check_buy(
                    symbol, settings.max_order_amount_krw,
                    balance_krw=_balance_krw,
                    active_positions=_active_positions,
                    already_holding=_already_holding,
                )
                if not check.allowed:
                    logger.warning("매수 차단: %s — %s", symbol, check.reason)
                    if bot:
                        bot.send_message(f"\u26a0\ufe0f <b>매수 차단</b>\n{symbol}: {check.reason}")
                    continue

            order = broker.buy_market(symbol, settings.max_order_amount_krw, ticker.price, reason=signal_result.reason)
            if order:
                logger.info("매수 체결: %s %s KRW [%s]", symbol, f"{settings.max_order_amount_krw:,.0f}", settings.trade_mode)

        elif broker and signal_result.action == "sell":
            if isinstance(broker, PaperBroker):
                pos = broker.positions.get(symbol)
                if pos and pos.quantity > 0:
                    order = broker.sell_market(symbol, pos.quantity, ticker.price, reason=signal_result.reason)
                    if order:
                        logger.info("매도 체결: %s %.8f [%s]", symbol, pos.quantity, settings.trade_mode)
                else:
                    logger.info("매도 시그널이지만 보유 수량 없음: %s", symbol)
            elif isinstance(broker, LiveBroker):
                # 실거래: 잔고에서 수량 조회
                currency = symbol.split("-")[1]
                balance = client.get_balance(currency)
                if balance and balance.available > 0:
                    order = broker.sell_market(symbol, balance.available, ticker.price, reason=signal_result.reason)
                    if order:
                        logger.info("매도 체결: %s %.8f [live]", symbol, balance.available)
                else:
                    logger.info("매도 시그널이지만 보유 수량 없음: %s", symbol)

        # 텔레그램 전송 (hold 제외)
        if bot and signal_result.action != "hold":
            bot.send_signal(signal_result, price=ticker.price)
        elif bot and signal_result.action == "hold":
            logger.info("관망 시그널 — 텔레그램 전송 생략")

    # Paper trading 요약
    if isinstance(broker, PaperBroker):
        prices = {}
        for symbol in symbols:
            ticker = client.get_ticker(symbol)
            prices[symbol] = ticker.price
        summary = broker.summary_text(prices)
        logger.info("=== Paper Trading 현황 ===\n%s", summary)
        if bot:
            bot.send_message(f"\U0001f4b0 <b>Paper Trading 현황</b>\n<pre>{summary}</pre>")


def strategy_job(
    client: UpbitClient,
    bot: TelegramBot | None,
    broker: BaseBroker | None,
    risk_guard: RiskGuard | None,
    symbols: list[str],
    settings,
):
    """스케줄러에서 호출되는 전략 래퍼. 에러 시 해당 주기만 스킵."""
    logger = setup_logger("cryptolight.main")
    try:
        run_strategy(client, bot, broker, risk_guard, symbols, settings)
    except Exception:
        logger.exception("전략 실행 중 에러 발생 — 이번 주기 스킵")


def command_job(cmd_handler: CommandHandler, scheduler: BlockingScheduler, bot: TelegramBot | None):
    """명령어 폴링 job. 킬스위치 감지 시 스케줄러 종료."""
    logger = setup_logger("cryptolight.main")
    try:
        cmd_handler.poll_commands()
        if cmd_handler.kill_switch:
            logger.warning("킬스위치 활성 — 스케줄러 종료 요청")
            if bot:
                bot.send_message("\u26d4 킬스위치 활성 — 봇을 종료합니다.")
            scheduler.shutdown(wait=False)
    except Exception:
        logger.exception("명령어 폴링 중 에러 발생")


def main():
    parser = argparse.ArgumentParser(description="cryptolight trading bot")
    parser.add_argument("--once", action="store_true", help="1회 실행 후 종료")
    args = parser.parse_args()

    settings = get_settings()
    logger = setup_logger("cryptolight.main", settings.log_level)

    once_mode = args.once or settings.schedule_interval_minutes == 0

    logger.info("cryptolight v0.1.0 시작")
    logger.info("거래 모드: %s", settings.trade_mode)
    logger.info("대상 종목: %s", settings.symbol_list)

    # 텔레그램 봇 초기화
    bot = None
    cmd_handler = None
    if settings.telegram_bot_token and settings.telegram_chat_id:
        bot = TelegramBot(settings.telegram_bot_token, settings.telegram_chat_id)
        cmd_handler = CommandHandler(settings.telegram_bot_token, settings.telegram_chat_id)
        bot.send_startup(settings.symbol_list, settings.trade_mode)
        logger.info("텔레그램 봇 연결됨")
    else:
        logger.warning("텔레그램 설정 없음 — 알림 비활성화")

    # 명령어 확인 (킬스위치)
    if cmd_handler:
        cmd_handler.poll_commands()
        if cmd_handler.kill_switch:
            logger.warning("킬스위치 활성 — 실행 중단")
            if bot:
                bot.close()
            cmd_handler.close()
            return

    # 브로커 초기화
    broker = None
    repo = TradeRepository(db_path=Path(settings.db_path))
    risk_guard = RiskGuard(
        max_order_amount_krw=settings.max_order_amount_krw,
        daily_loss_limit_krw=settings.daily_loss_limit_krw,
        max_positions=settings.max_positions,
        stop_loss_pct=settings.stop_loss_pct,
        take_profit_pct=settings.take_profit_pct,
        repo=repo,
    )

    client = UpbitClient(settings.upbit_access_key, settings.upbit_secret_key)

    if settings.trade_mode == "paper":
        broker = PaperBroker(initial_balance=settings.paper_initial_balance, repo=repo)
        logger.info("Paper trading 초기화: 초기 자금 %s KRW", f"{broker.initial_balance:,.0f}")
    elif settings.trade_mode == "live":
        broker = LiveBroker(client=client, repo=repo)
        logger.info("Live trading 초기화")
        if bot:
            bot.send_message("\u26a0\ufe0f <b>LIVE 모드</b>로 실행 중입니다.")

    logger.info(
        "리스크 설정: 최대주문 %s, 일일손실한도 %s, 손절 %s%%, 익절 %s%%",
        f"{settings.max_order_amount_krw:,.0f}",
        f"{settings.daily_loss_limit_krw:,.0f}",
        settings.stop_loss_pct,
        settings.take_profit_pct,
    )

    # ── 1회 실행 모드 ──
    if once_mode:
        logger.info("1회 실행 모드")
        try:
            run_strategy(client, bot, broker, risk_guard, settings.symbol_list, settings)
        finally:
            if bot:
                bot.close()
            if cmd_handler:
                cmd_handler.close()
            client.close()
            repo.close()
        logger.info("cryptolight 종료")
        return

    # ── 스케줄러 모드 ──
    logger.info("스케줄러 모드: %d분 간격", settings.schedule_interval_minutes)
    scheduler = BlockingScheduler()

    scheduler.add_job(
        strategy_job,
        "interval",
        minutes=settings.schedule_interval_minutes,
        max_instances=1,
        args=[client, bot, broker, risk_guard, settings.symbol_list, settings],
        id="strategy",
        next_run_time=None,  # 첫 실행은 아래에서 즉시 수행
    )

    if cmd_handler:
        scheduler.add_job(
            command_job,
            "interval",
            seconds=settings.command_poll_seconds,
            max_instances=1,
            args=[cmd_handler, scheduler, bot],
            id="command_poll",
        )

    # Graceful shutdown
    def _shutdown(signum, _frame):
        sig_name = signal.Signals(signum).name
        logger.info("시그널 수신: %s — graceful shutdown", sig_name)
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # 스케줄러 시작 전 1회 즉시 실행
    strategy_job(client, bot, broker, risk_guard, settings.symbol_list, settings)

    try:
        # next_run_time을 설정하여 다음 interval부터 실행되도록
        scheduler.reschedule_job("strategy", trigger="interval", minutes=settings.schedule_interval_minutes)
        scheduler.start()
    finally:
        logger.info("스케줄러 종료 — 리소스 정리")
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
