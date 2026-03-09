"""cryptolight 진입점 - 거래소 연결 확인 및 기본 동작"""

from cryptolight.config import get_settings
from cryptolight.exchange.upbit import UpbitClient
from cryptolight.utils import setup_logger


def show_balances(client: UpbitClient):
    logger = setup_logger("cryptolight.main")
    balances = client.get_balances()
    logger.info("=== 보유 자산 ===")
    for b in balances:
        logger.info("  %s: %.8f (가용: %.8f, 평균매수가: %.0f)", b.currency, b.total, b.available, b.avg_buy_price)


def show_ticker(client: UpbitClient, symbols: list[str]):
    logger = setup_logger("cryptolight.main")
    logger.info("=== 현재가 ===")
    for symbol in symbols:
        ticker = client.get_ticker(symbol)
        logger.info(
            "  %s: %s KRW (변동: %+.2f%%, 24h거래량: %.2f)",
            ticker.symbol, f"{ticker.price:,.0f}", ticker.change_rate * 100, ticker.volume_24h,
        )


def show_candles(client: UpbitClient, symbol: str, count: int = 5):
    logger = setup_logger("cryptolight.main")
    candles = client.get_candles(symbol, interval="day", count=count)
    logger.info("=== %s 최근 %d일 캔들 ===", symbol, count)
    for c in candles:
        logger.info(
            "  %s | O:%s H:%s L:%s C:%s V:%.2f",
            c.timestamp, f"{c.open:,.0f}", f"{c.high:,.0f}", f"{c.low:,.0f}", f"{c.close:,.0f}", c.volume,
        )


def main():
    settings = get_settings()
    logger = setup_logger("cryptolight.main", settings.log_level)

    logger.info("cryptolight v0.1.0 시작")
    logger.info("거래 모드: %s", settings.trade_mode)
    logger.info("대상 종목: %s", settings.symbol_list)

    if not settings.upbit_access_key or not settings.upbit_secret_key:
        logger.warning("업비트 API 키가 설정되지 않았습니다. 공개 API만 사용합니다.")

    with UpbitClient(settings.upbit_access_key, settings.upbit_secret_key) as client:
        # 현재가 조회 (공개 API - 키 없어도 가능)
        show_ticker(client, settings.symbol_list)

        # 캔들 조회 (공개 API)
        for symbol in settings.symbol_list:
            show_candles(client, symbol, count=5)

        # 잔고 조회 (인증 필요)
        if settings.upbit_access_key:
            show_balances(client)

    logger.info("cryptolight 종료")


if __name__ == "__main__":
    main()
