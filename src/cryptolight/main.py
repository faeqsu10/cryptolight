"""cryptolight 진입점 - 전략 실행 및 시그널 알림"""

from cryptolight.bot.telegram_bot import TelegramBot
from cryptolight.config import get_settings
from cryptolight.exchange.upbit import UpbitClient
from cryptolight.strategy.rsi import RSIStrategy
from cryptolight.utils import setup_logger


def run_strategy(client: UpbitClient, bot: TelegramBot | None, symbols: list[str]):
    """각 종목에 대해 전략을 실행하고 시그널을 전송한다."""
    logger = setup_logger("cryptolight.main")
    strategy = RSIStrategy(period=14, oversold=30, overbought=70)

    for symbol in symbols:
        # 캔들 조회 (전략에 필요한 수량)
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
            signal.action.upper(),
            symbol,
            signal.reason,
            signal.confidence * 100,
            signal.indicators.get("rsi", "N/A"),
        )

        # 텔레그램 전송 (hold 제외)
        if bot and signal.action != "hold":
            bot.send_signal(signal, price=ticker.price)
            logger.info("텔레그램 시그널 전송 완료: %s %s", signal.action, symbol)
        elif bot and signal.action == "hold":
            logger.info("관망 시그널 — 텔레그램 전송 생략")


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

    try:
        with UpbitClient(settings.upbit_access_key, settings.upbit_secret_key) as client:
            run_strategy(client, bot, settings.symbol_list)
    finally:
        if bot:
            bot.close()

    logger.info("cryptolight 종료")


if __name__ == "__main__":
    main()
