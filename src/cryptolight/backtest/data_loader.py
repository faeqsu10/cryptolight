import logging
import time

from cryptolight.exchange.base import Candle
from cryptolight.exchange.upbit import UpbitClient

logger = logging.getLogger("cryptolight.backtest.data_loader")


def load_candles(
    client: UpbitClient, symbol: str, days: int, interval: str = "day",
) -> list[Candle]:
    """업비트에서 과거 캔들을 페이지네이션으로 가져온다.

    200개씩 반복 조회하며, 오래된 순으로 정렬하여 반환한다.
    """
    all_candles: list[Candle] = []
    remaining = days
    to: str | None = None

    while remaining > 0:
        fetch_count = min(remaining, 200)
        candles = client.get_candles(
            symbol=symbol, interval=interval, count=fetch_count, to=to,
        )

        if not candles:
            break

        all_candles = candles + all_candles  # 앞에 추가 (오래된 순)
        remaining -= len(candles)

        if len(candles) < fetch_count:
            # 더 이상 데이터가 없음
            break

        # 다음 페이지: 이번 결과의 가장 오래된 캔들 타임스탬프
        to = candles[0].timestamp

        logger.info(
            "%s %d개 로드 (누적 %d / %d)", symbol, len(candles), len(all_candles), days,
        )
        time.sleep(0.2)  # rate limit 대응

    logger.info("캔들 로드 완료: %s 총 %d개", symbol, len(all_candles))
    return all_candles
