"""python -m cryptolight.backtest 으로 실행"""
import argparse
import logging

from cryptolight.backtest.data_loader import load_candles
from cryptolight.backtest.engine import BacktestEngine
from cryptolight.bot.telegram_bot import TelegramBot
from cryptolight.config import get_settings
from cryptolight.exchange.upbit import UpbitClient
from cryptolight.strategy import create_strategy
from cryptolight.utils.logger import setup_logger


def main():
    parser = argparse.ArgumentParser(description="cryptolight 백테스트")
    parser.add_argument("--symbol", default="KRW-BTC")
    parser.add_argument("--strategy", default="rsi")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--balance", type=float, default=1_000_000)
    parser.add_argument("--amount", type=float, default=50_000)
    parser.add_argument("--telegram", action="store_true", help="결과를 텔레그램으로 전송")
    args = parser.parse_args()

    setup_logger(level="INFO")
    logger = logging.getLogger("cryptolight.backtest")

    settings = get_settings()
    strategy = create_strategy(args.strategy)

    logger.info(
        "백테스트 시작: %s / %s / %d일 / 초기자산 %s",
        args.symbol, args.strategy, args.days, f"{args.balance:,.0f}",
    )

    # 캔들 로드
    client = UpbitClient(
        access_key=settings.upbit_access_key,
        secret_key=settings.upbit_secret_key,
    )
    try:
        candles = load_candles(client, args.symbol, args.days)
    finally:
        client.close()

    if len(candles) < strategy.required_candle_count():
        logger.error(
            "캔들 부족: %d개 (최소 %d개 필요)",
            len(candles), strategy.required_candle_count(),
        )
        return

    logger.info("캔들 %d개 로드 완료, 백테스트 실행 중...", len(candles))

    # 백테스트 실행 (슬리피지/스프레드 설정 반영)
    engine = BacktestEngine(
        strategy=strategy,
        initial_balance=args.balance,
        order_amount=args.amount,
        slippage_pct=settings.backtest_slippage_pct,
        spread_pct=settings.backtest_spread_pct,
    )
    result = engine.run(candles)
    summary = engine.summary_text(result)

    print()
    print(summary)

    # 텔레그램 전송
    if args.telegram and settings.telegram_bot_token and settings.telegram_chat_id:
        bot = TelegramBot(
            token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
        )
        try:
            header = f"<b>백테스트 결과</b>\n{args.symbol} / {args.strategy} / {args.days}일\n\n"
            bot.send_message(header + summary)
            logger.info("텔레그램 전송 완료")
        finally:
            bot.close()


if __name__ == "__main__":
    main()
