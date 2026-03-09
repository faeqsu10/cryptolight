"""cryptolight 진입점 - 전략 실행, 시그널 알림, paper trading"""

from cryptolight.bot.telegram_bot import TelegramBot
from cryptolight.config import get_settings
from cryptolight.exchange.upbit import UpbitClient
from cryptolight.execution.paper_broker import PaperBroker
from cryptolight.storage.repository import TradeRepository
from cryptolight.strategy.rsi import RSIStrategy
from cryptolight.utils import setup_logger


def run_strategy(
    client: UpbitClient,
    bot: TelegramBot | None,
    broker: PaperBroker | None,
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

        # 전략 분석
        signal = strategy.analyze(candles)
        signal.symbol = symbol

        logger.info(
            "[%s] %s — %s (신뢰도: %.0f%%, RSI: %s)",
            signal.action.upper(), symbol, signal.reason,
            signal.confidence * 100, signal.indicators.get("rsi", "N/A"),
        )

        # Paper trading 실행
        if broker and signal.action == "buy":
            order = broker.buy_market(
                symbol, settings.max_order_amount_krw, ticker.price, reason=signal.reason,
            )
            if order:
                logger.info("Paper 매수 체결: %s %s", symbol, f"{settings.max_order_amount_krw:,.0f} KRW")
        elif broker and signal.action == "sell":
            pos = broker.positions.get(symbol)
            if pos and pos.quantity > 0:
                order = broker.sell_market(symbol, pos.quantity, ticker.price, reason=signal.reason)
                if order:
                    logger.info("Paper 매도 체결: %s %.8f", symbol, pos.quantity)
            else:
                logger.info("매도 시그널이지만 보유 수량 없음: %s", symbol)

        # 텔레그램 전송 (hold 제외)
        if bot and signal.action != "hold":
            bot.send_signal(signal, price=ticker.price)
        elif bot and signal.action == "hold":
            logger.info("관망 시그널 — 텔레그램 전송 생략")

    # Paper trading 요약
    if broker:
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
    if settings.telegram_bot_token and settings.telegram_chat_id:
        bot = TelegramBot(settings.telegram_bot_token, settings.telegram_chat_id)
        bot.send_startup(settings.symbol_list, settings.trade_mode)
        logger.info("텔레그램 봇 연결됨")
    else:
        logger.warning("텔레그램 설정 없음 — 알림 비활성화")

    # Paper trading 초기화
    broker = None
    repo = None
    if settings.trade_mode == "paper":
        repo = TradeRepository()
        broker = PaperBroker(initial_balance=1_000_000, repo=repo)
        logger.info("Paper trading 초기화: 초기 자금 %s KRW", f"{broker.initial_balance:,.0f}")

    try:
        with UpbitClient(settings.upbit_access_key, settings.upbit_secret_key) as client:
            run_strategy(client, bot, broker, settings.symbol_list, settings)
    finally:
        if bot:
            bot.close()
        if repo:
            repo.close()

    logger.info("cryptolight 종료")


if __name__ == "__main__":
    main()
