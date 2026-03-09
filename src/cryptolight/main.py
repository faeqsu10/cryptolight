"""cryptolight 진입점 - 전략 실행, 시그널 알림, paper/live trading, 리스크 관리"""

from cryptolight.bot.command_handler import CommandHandler
from cryptolight.bot.telegram_bot import TelegramBot
from cryptolight.config import get_settings
from cryptolight.exchange.upbit import UpbitClient
from cryptolight.execution.live_broker import LiveBroker
from cryptolight.execution.paper_broker import PaperBroker
from cryptolight.risk.risk_guard import RiskGuard
from cryptolight.storage.repository import TradeRepository
from cryptolight.strategy.rsi import RSIStrategy
from cryptolight.utils import setup_logger


def run_strategy(
    client: UpbitClient,
    bot: TelegramBot | None,
    broker: PaperBroker | LiveBroker | None,
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
            sl_tp = risk_guard.check_stop_loss_take_profit(symbol, broker, ticker.price)
            if sl_tp == "stop_loss":
                pos = broker.positions[symbol]
                order = broker.sell_market(symbol, pos.quantity, ticker.price, reason="손절 트리거")
                if order:
                    logger.warning("손절 매도 실행: %s %.8f @ %s", symbol, pos.quantity, f"{ticker.price:,.0f}")
                    if bot:
                        bot.send_message(f"\U0001f534 <b>손절 매도</b>\n{symbol} @ {ticker.price:,.0f} KRW")
                continue
            elif sl_tp == "take_profit":
                pos = broker.positions[symbol]
                order = broker.sell_market(symbol, pos.quantity, ticker.price, reason="익절 트리거")
                if order:
                    logger.info("익절 매도 실행: %s %.8f @ %s", symbol, pos.quantity, f"{ticker.price:,.0f}")
                    if bot:
                        bot.send_message(f"\U0001f7e2 <b>익절 매도</b>\n{symbol} @ {ticker.price:,.0f} KRW")
                continue

        # 전략 분석
        signal = strategy.analyze(candles)
        signal.symbol = symbol

        logger.info(
            "[%s] %s — %s (신뢰도: %.0f%%, RSI: %s)",
            signal.action.upper(), symbol, signal.reason,
            signal.confidence * 100, signal.indicators.get("rsi", "N/A"),
        )

        # 매수 실행
        if broker and signal.action == "buy":
            # 리스크 체크 (paper 모드)
            if isinstance(broker, PaperBroker) and risk_guard:
                check = risk_guard.check_buy(symbol, settings.max_order_amount_krw, broker)
                if not check.allowed:
                    logger.warning("매수 차단: %s — %s", symbol, check.reason)
                    if bot:
                        bot.send_message(f"\u26a0\ufe0f <b>매수 차단</b>\n{symbol}: {check.reason}")
                    continue

            order = broker.buy_market(symbol, settings.max_order_amount_krw, ticker.price, reason=signal.reason)
            if order:
                logger.info("매수 체결: %s %s KRW [%s]", symbol, f"{settings.max_order_amount_krw:,.0f}", settings.trade_mode)

        elif broker and signal.action == "sell":
            if isinstance(broker, PaperBroker):
                pos = broker.positions.get(symbol)
                if pos and pos.quantity > 0:
                    order = broker.sell_market(symbol, pos.quantity, ticker.price, reason=signal.reason)
                    if order:
                        logger.info("매도 체결: %s %.8f [%s]", symbol, pos.quantity, settings.trade_mode)
                else:
                    logger.info("매도 시그널이지만 보유 수량 없음: %s", symbol)
            elif isinstance(broker, LiveBroker):
                # 실거래: 잔고에서 수량 조회
                currency = symbol.split("-")[1]
                balance = client.get_balance(currency)
                if balance and balance.available > 0:
                    order = broker.sell_market(symbol, balance.available, ticker.price, reason=signal.reason)
                    if order:
                        logger.info("매도 체결: %s %.8f [live]", symbol, balance.available)
                else:
                    logger.info("매도 시그널이지만 보유 수량 없음: %s", symbol)

        # 텔레그램 전송 (hold 제외)
        if bot and signal.action != "hold":
            bot.send_signal(signal, price=ticker.price)
        elif bot and signal.action == "hold":
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


def main():
    settings = get_settings()
    logger = setup_logger("cryptolight.main", settings.log_level)

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
    repo = None
    risk_guard = None

    repo = TradeRepository()
    risk_guard = RiskGuard(
        max_order_amount_krw=settings.max_order_amount_krw,
        daily_loss_limit_krw=settings.daily_loss_limit_krw,
        max_positions=settings.max_positions,
        stop_loss_pct=settings.stop_loss_pct,
        take_profit_pct=settings.take_profit_pct,
        repo=repo,
    )

    try:
        with UpbitClient(settings.upbit_access_key, settings.upbit_secret_key) as client:
            if settings.trade_mode == "paper":
                broker = PaperBroker(initial_balance=1_000_000, repo=repo)
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

            run_strategy(client, bot, broker, risk_guard, settings.symbol_list, settings)
    finally:
        if bot:
            bot.close()
        if cmd_handler:
            cmd_handler.close()
        if repo:
            repo.close()

    logger.info("cryptolight 종료")


if __name__ == "__main__":
    main()
