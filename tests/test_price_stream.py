"""PriceStream 단위 테스트 — WebSocket 콜백, 재연결 로직 검증"""

import json
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from cryptolight.market.price_stream import PriceStream


class TestPriceStreamCallback:
    """콜백 동작 검증"""

    def test_on_message_calls_callback(self):
        """SIMPLE 포맷 메시지 수신 시 on_price 콜백이 호출된다."""
        received = []

        def on_price(symbol, price, data):
            received.append((symbol, price))

        stream = PriceStream(
            symbols=["KRW-BTC"],
            on_price_callback=on_price,
        )

        # _on_message 직접 호출 (WebSocket 없이 단위 테스트)
        msg = json.dumps({"cd": "KRW-BTC", "tp": 95000000.0}).encode("utf-8")
        stream._on_message(None, msg)

        assert len(received) == 1
        assert received[0] == ("KRW-BTC", 95000000.0)

    def test_on_message_string_format(self):
        """문자열 메시지도 처리한다."""
        received = []

        def on_price(symbol, price, data):
            received.append((symbol, price))

        stream = PriceStream(symbols=["KRW-ETH"], on_price_callback=on_price)
        msg = json.dumps({"cd": "KRW-ETH", "tp": 4500000})
        stream._on_message(None, msg)

        assert received[0] == ("KRW-ETH", 4500000.0)

    def test_on_message_missing_fields_ignored(self):
        """cd 또는 tp 없는 메시지는 무시한다."""
        received = []

        def on_price(symbol, price, data):
            received.append((symbol, price))

        stream = PriceStream(symbols=["KRW-BTC"], on_price_callback=on_price)
        stream._on_message(None, json.dumps({"type": "heartbeat"}).encode("utf-8"))

        assert len(received) == 0

    def test_on_message_invalid_json(self):
        """잘못된 JSON은 에러 없이 무시한다."""
        stream = PriceStream(symbols=["KRW-BTC"], on_price_callback=lambda *a: None)
        # 예외가 발생하지 않아야 함
        stream._on_message(None, b"not-json")

    def test_multiple_symbols(self):
        """여러 종목 메시지를 구분하여 콜백한다."""
        received = []

        def on_price(symbol, price, data):
            received.append(symbol)

        stream = PriceStream(
            symbols=["KRW-BTC", "KRW-ETH"],
            on_price_callback=on_price,
        )
        stream._on_message(None, json.dumps({"cd": "KRW-BTC", "tp": 95000000}).encode())
        stream._on_message(None, json.dumps({"cd": "KRW-ETH", "tp": 4500000}).encode())

        assert received == ["KRW-BTC", "KRW-ETH"]


class TestPriceStreamConnection:
    """연결/해제 콜백 검증"""

    def test_on_open_sets_connected(self):
        """on_open 호출 시 is_connected가 True가 된다."""
        connect_called = []

        stream = PriceStream(
            symbols=["KRW-BTC"],
            on_price_callback=lambda *a: None,
            on_connect=lambda: connect_called.append(True),
        )
        assert not stream.is_connected

        mock_ws = MagicMock()
        stream._on_open(mock_ws)

        assert stream.is_connected
        assert len(connect_called) == 1
        # 구독 메시지 전송 확인
        mock_ws.send.assert_called_once()
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert sent[1]["type"] == "ticker"
        assert sent[1]["codes"] == ["KRW-BTC"]

    def test_on_close_sets_disconnected(self):
        """on_close 호출 시 is_connected가 False가 된다."""
        disconnect_called = []

        stream = PriceStream(
            symbols=["KRW-BTC"],
            on_price_callback=lambda *a: None,
            on_disconnect=lambda: disconnect_called.append(True),
        )
        stream._connected = True

        stream._on_close(None, 1000, "normal")

        assert not stream.is_connected
        assert len(disconnect_called) == 1

    def test_on_close_no_callback_when_not_connected(self):
        """이미 연결되지 않은 상태에서 on_close는 disconnect 콜백을 호출하지 않는다."""
        disconnect_called = []

        stream = PriceStream(
            symbols=["KRW-BTC"],
            on_price_callback=lambda *a: None,
            on_disconnect=lambda: disconnect_called.append(True),
        )
        stream._connected = False

        stream._on_close(None, 1000, "normal")

        assert len(disconnect_called) == 0

    def test_reconnect_delay_resets_on_connect(self):
        """연결 성공 시 재연결 지연이 1초로 초기화된다."""
        stream = PriceStream(
            symbols=["KRW-BTC"],
            on_price_callback=lambda *a: None,
        )
        stream._reconnect_delay = 32.0  # 여러 번 실패 후 높아진 상태

        mock_ws = MagicMock()
        stream._on_open(mock_ws)

        assert stream._reconnect_delay == 1.0

    def test_on_error_does_not_crash(self):
        """on_error는 에러 없이 처리된다."""
        stream = PriceStream(symbols=["KRW-BTC"], on_price_callback=lambda *a: None)
        stream._on_error(None, Exception("test error"))


class TestPriceStreamLifecycle:
    """start/stop 라이프사이클"""

    @patch("cryptolight.market.price_stream.websocket.WebSocketApp")
    def test_start_creates_daemon_thread(self, mock_ws_cls):
        """start() 호출 시 daemon 스레드가 생성된다."""
        mock_ws_cls.return_value.run_forever = MagicMock(
            side_effect=lambda **kw: time.sleep(0.1)
        )

        stream = PriceStream(
            symbols=["KRW-BTC"],
            on_price_callback=lambda *a: None,
        )
        stream.start()
        time.sleep(0.05)

        assert stream._thread is not None
        assert stream._thread.daemon is True
        assert stream._thread.name == "price-stream"

        stream.stop()

    def test_stop_without_start(self):
        """start 없이 stop 호출해도 에러 없다."""
        stream = PriceStream(symbols=["KRW-BTC"], on_price_callback=lambda *a: None)
        stream.stop()  # 에러 없어야 함

    @patch("cryptolight.market.price_stream.websocket.WebSocketApp")
    def test_double_start_warns(self, mock_ws_cls):
        """이미 실행 중일 때 start()는 경고만 한다."""
        mock_ws_cls.return_value.run_forever = MagicMock(
            side_effect=lambda **kw: time.sleep(0.5)
        )

        stream = PriceStream(
            symbols=["KRW-BTC"],
            on_price_callback=lambda *a: None,
        )
        stream.start()
        time.sleep(0.05)
        stream.start()  # 두 번째 호출 — 경고만

        stream.stop()


class TestPriceStreamReconnect:
    """재연결 백오프 로직"""

    def test_backoff_doubles(self):
        """_run_loop에서 연결 실패 시 지연이 2배씩 증가한다."""
        stream = PriceStream(
            symbols=["KRW-BTC"],
            on_price_callback=lambda *a: None,
            reconnect_max_seconds=16,
        )

        delays = []
        call_count = 0

        def fake_connect():
            nonlocal call_count
            delays.append(stream._reconnect_delay)
            call_count += 1
            if call_count >= 4:
                stream._stop_event.set()
            raise ConnectionError("test")

        stream._connect = fake_connect
        stream._run_loop()

        # 초기값 1 → 실패 후 2 → 4 → 8
        assert delays == [1.0, 2.0, 4.0, 8.0]

    def test_backoff_caps_at_max(self):
        """재연결 지연은 max 값을 초과하지 않는다."""
        stream = PriceStream(
            symbols=["KRW-BTC"],
            on_price_callback=lambda *a: None,
            reconnect_max_seconds=4,
        )

        call_count = 0

        def fake_connect():
            nonlocal call_count
            call_count += 1
            if call_count >= 6:
                stream._stop_event.set()
            raise ConnectionError("test")

        stream._connect = fake_connect
        stream._run_loop()

        assert stream._reconnect_delay <= 4
