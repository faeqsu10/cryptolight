"""업비트 WebSocket 실시간 가격 스트림 — 손절/익절 즉시 반응용"""

import json
import logging
import threading
import uuid
from typing import Callable

import websocket

logger = logging.getLogger("cryptolight.market.price_stream")

UPBIT_WS_URL = "wss://api.upbit.com/websocket/v1"


class PriceStream:
    """업비트 WebSocket으로 실시간 체결가를 수신하고 콜백을 호출한다.

    - 전용 daemon 스레드에서 동작
    - 연결 끊김 시 지수 백오프 재연결
    - on_price_callback(symbol, price, data) 호출
    - on_connect / on_disconnect 콜백으로 fallback 전환 가능
    """

    def __init__(
        self,
        symbols: list[str],
        on_price_callback: Callable[[str, float, dict], None],
        on_connect: Callable[[], None] | None = None,
        on_disconnect: Callable[[], None] | None = None,
        reconnect_max_seconds: int = 60,
    ):
        self._symbols = symbols
        self._on_price = on_price_callback
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._reconnect_max = reconnect_max_seconds

        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._connected = False
        self._reconnect_delay = 1.0

    @property
    def is_connected(self) -> bool:
        return self._connected

    def start(self):
        """WebSocket 수신 스레드를 시작한다."""
        if self._thread and self._thread.is_alive():
            logger.warning("PriceStream 이미 실행 중")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="price-stream",
        )
        self._thread.start()
        logger.info("PriceStream 스레드 시작: %s", self._symbols)

    def stop(self):
        """WebSocket 연결을 종료한다."""
        self._stop_event.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._connected = False
        logger.info("PriceStream 종료")

    def _run_loop(self):
        """재연결 루프 — stop 요청까지 반복."""
        while not self._stop_event.is_set():
            try:
                self._connect()
            except Exception:
                logger.exception("WebSocket 연결 실패")

            if self._stop_event.is_set():
                break

            # 지수 백오프 재연결
            delay = self._reconnect_delay
            logger.info("WebSocket 재연결 대기: %.1f초", delay)
            self._stop_event.wait(delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, self._reconnect_max)

    def _connect(self):
        """WebSocket 연결을 생성하고 run_forever로 블로킹."""
        self._ws = websocket.WebSocketApp(
            UPBIT_WS_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._ws.run_forever(
            ping_interval=30,
            ping_timeout=10,
        )

    def _on_open(self, ws):
        """연결 성공 시 구독 메시지 전송."""
        subscribe = [
            {"ticket": str(uuid.uuid4())},
            {
                "type": "ticker",
                "codes": self._symbols,
                "isOnlyRealtime": True,
            },
            {"format": "SIMPLE"},
        ]
        ws.send(json.dumps(subscribe))
        self._connected = True
        self._reconnect_delay = 1.0  # 성공 시 백오프 초기화
        logger.info("WebSocket 연결 성공: %d개 종목 구독", len(self._symbols))
        if self._on_connect:
            try:
                self._on_connect()
            except Exception:
                logger.exception("on_connect 콜백 에러")

    def _on_message(self, ws, message):
        """체결 데이터 수신 → 콜백 호출."""
        try:
            if isinstance(message, bytes):
                data = json.loads(message.decode("utf-8"))
            else:
                data = json.loads(message)

            # SIMPLE 포맷: cd=종목코드, tp=체결가
            symbol = data.get("cd")
            price = data.get("tp")
            if symbol and price:
                self._on_price(symbol, float(price), data)
        except Exception:
            logger.exception("WebSocket 메시지 처리 에러")

    def _on_error(self, ws, error):
        logger.warning("WebSocket 에러: %s", error)

    def _on_close(self, ws, close_status_code, close_msg):
        was_connected = self._connected
        self._connected = False
        logger.info(
            "WebSocket 연결 종료 (code=%s, msg=%s)",
            close_status_code, close_msg,
        )
        if was_connected and self._on_disconnect:
            try:
                self._on_disconnect()
            except Exception:
                logger.exception("on_disconnect 콜백 에러")
