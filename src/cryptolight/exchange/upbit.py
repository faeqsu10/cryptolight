import hashlib
import logging
import time
import uuid
from urllib.parse import urlencode

import httpx
import jwt

from cryptolight.exchange.base import (
    Balance,
    Candle,
    ExchangeClient,
    OrderResult,
    Ticker,
)

logger = logging.getLogger("cryptolight.exchange.upbit")

BASE_URL = "https://api.upbit.com/v1"


class UpbitClient(ExchangeClient):
    _MAX_RETRIES = 3
    _BACKOFF_BASE = 1  # 초

    def __init__(self, access_key: str, secret_key: str):
        self._access_key = access_key
        self._secret_key = secret_key
        self._client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        self._consecutive_errors: int = 0

    # ── 인증 ──

    def _auth_header(self, params: dict | None = None) -> dict[str, str]:
        payload: dict = {
            "access_key": self._access_key,
            "nonce": str(uuid.uuid4()),
        }
        if params:
            query_string = urlencode(params).encode()
            m = hashlib.sha512()
            m.update(query_string)
            payload["query_hash"] = m.hexdigest()
            payload["query_hash_alg"] = "SHA512"

        token = jwt.encode(payload, self._secret_key, algorithm="HS256")
        return {"Authorization": f"Bearer {token}"}

    # ── HTTP 공통 ──

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        auth: bool = False,
    ) -> dict | list:
        """HTTP 요청을 실행한다. 최대 3회 재시도, 지수 백오프."""
        last_exc: Exception | None = None

        for attempt in range(self._MAX_RETRIES):
            try:
                headers = self._auth_header(params or json_body) if auth else {}
                resp = self._client.request(
                    method, path, params=params, json=json_body, headers=headers,
                )
                resp.raise_for_status()
                self._consecutive_errors = 0
                return resp.json()

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 429:
                    # Retry-After 헤더 준수
                    retry_after = float(exc.response.headers.get("Retry-After", self._BACKOFF_BASE * 2**attempt))
                    logger.warning("429 Too Many Requests — %s초 후 재시도 (%d/%d)", retry_after, attempt + 1, self._MAX_RETRIES)
                    time.sleep(retry_after)
                    last_exc = exc
                elif status >= 500:
                    wait = self._BACKOFF_BASE * 2**attempt
                    logger.warning("%d 서버 에러 — %s초 후 재시도 (%d/%d)", status, wait, attempt + 1, self._MAX_RETRIES)
                    time.sleep(wait)
                    last_exc = exc
                else:
                    # 4xx (429 제외) → 즉시 raise
                    self._consecutive_errors += 1
                    if self._consecutive_errors >= 5:
                        logger.error("연속 에러 %d회 도달", self._consecutive_errors)
                    raise

            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                wait = self._BACKOFF_BASE * 2**attempt
                logger.warning("%s — %s초 후 재시도 (%d/%d)", type(exc).__name__, wait, attempt + 1, self._MAX_RETRIES)
                time.sleep(wait)
                last_exc = exc

        # 모든 재시도 소진
        self._consecutive_errors += 1
        if self._consecutive_errors >= 5:
            logger.error("연속 에러 %d회 도달", self._consecutive_errors)
        raise last_exc  # type: ignore[misc]

    def _get(self, path: str, params: dict | None = None, auth: bool = False) -> dict | list:
        return self._request("GET", path, params=params, auth=auth)

    def _post(self, path: str, body: dict) -> dict:
        return self._request("POST", path, json_body=body, auth=True)

    def _delete(self, path: str, params: dict) -> dict:
        return self._request("DELETE", path, params=params, auth=True)

    # ── 잔고 ──

    def get_balances(self) -> list[Balance]:
        data = self._get("/accounts", auth=True)
        return [
            Balance(
                currency=item["currency"],
                total=float(item["balance"]) + float(item["locked"]),
                available=float(item["balance"]),
                locked=float(item["locked"]),
                avg_buy_price=float(item.get("avg_buy_price", 0)),
            )
            for item in data
        ]

    def get_balance(self, currency: str) -> Balance | None:
        for b in self.get_balances():
            if b.currency == currency.upper():
                return b
        return None

    # ── 시세 ──

    def get_candles(
        self, symbol: str, interval: str = "day", count: int = 200
    ) -> list[Candle]:
        if interval == "day":
            path = "/candles/days"
            params = {"market": symbol, "count": min(count, 200)}
        elif interval.startswith("minute"):
            unit = interval.replace("minute", "") or "1"
            path = f"/candles/minutes/{unit}"
            params = {"market": symbol, "count": min(count, 200)}
        else:
            path = "/candles/days"
            params = {"market": symbol, "count": min(count, 200)}

        data = self._get(path, params=params)
        candles = [
            Candle(
                timestamp=item["candle_date_time_kst"],
                open=float(item["opening_price"]),
                high=float(item["high_price"]),
                low=float(item["low_price"]),
                close=float(item["trade_price"]),
                volume=float(item["candle_acc_trade_volume"]),
            )
            for item in data
        ]
        candles.reverse()  # 오래된 순으로 정렬
        return candles

    def get_ticker(self, symbol: str) -> Ticker:
        data = self._get("/ticker", params={"markets": symbol})
        item = data[0]
        return Ticker(
            symbol=symbol,
            price=float(item["trade_price"]),
            change_rate=float(item.get("signed_change_rate", 0)),
            volume_24h=float(item.get("acc_trade_volume_24h", 0)),
            high_24h=float(item.get("high_price", 0)),
            low_24h=float(item.get("low_price", 0)),
        )

    # ── 주문 ──

    def buy_market(self, symbol: str, amount_krw: float) -> OrderResult:
        body = {
            "market": symbol,
            "side": "bid",
            "ord_type": "price",  # 시장가 매수 = 금액 기준
            "price": str(amount_krw),
        }
        logger.info("시장가 매수 요청: %s %.0f KRW", symbol, amount_krw)
        return self._parse_order(self._post("/orders", body))

    def sell_market(self, symbol: str, quantity: float) -> OrderResult:
        body = {
            "market": symbol,
            "side": "ask",
            "ord_type": "market",  # 시장가 매도 = 수량 기준
            "volume": str(quantity),
        }
        logger.info("시장가 매도 요청: %s %.8f", symbol, quantity)
        return self._parse_order(self._post("/orders", body))

    def get_order(self, order_id: str) -> OrderResult:
        params = {"uuid": order_id}
        return self._parse_order(self._get("/order", params=params, auth=True))

    def cancel_order(self, order_id: str) -> OrderResult:
        params = {"uuid": order_id}
        logger.info("주문 취소 요청: %s", order_id)
        return self._parse_order(self._delete("/order", params=params))

    def get_order_chance(self, symbol: str) -> dict:
        params = {"market": symbol}
        return self._get("/orders/chance", params=params, auth=True)

    # ── 내부 ──

    def _parse_order(self, data: dict | list) -> OrderResult:
        if isinstance(data, list):
            data = data[0]
        return OrderResult(
            order_id=data.get("uuid", ""),
            symbol=data.get("market", ""),
            side=data.get("side", ""),
            order_type=data.get("ord_type", ""),
            price=float(data["price"]) if data.get("price") else None,
            quantity=float(data["volume"]) if data.get("volume") else None,
            amount=float(data["price"]) if data.get("side") == "bid" else None,
            state=data.get("state", ""),
            raw=data,
        )

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
