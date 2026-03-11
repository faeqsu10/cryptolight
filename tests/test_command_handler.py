import threading

from cryptolight.bot.command_handler import CommandHandler


def _make_handler() -> CommandHandler:
    handler = object.__new__(CommandHandler)
    handler._token = "token"
    handler._chat_id = "123"
    handler._base_url = "https://example.test"
    handler._client = None
    handler._poll_timeout_seconds = 20
    handler._lock = threading.Lock()
    handler._last_update_id = 0
    handler._last_poll_ok = True
    handler._kill_switch = False
    handler._report_requested = False
    handler._status_requested = False
    handler._info_requested = False
    handler._criteria_requested = False
    handler._tuning_requested = False
    handler._ask_queue = []
    handler._muted = False
    handler._send = lambda text: None
    return handler


def test_ask_command_enqueues_question_and_clears_after_read():
    handler = _make_handler()

    handler._handle_command("/ask", "/ask BTC RSI 설명해줘")

    assert handler.get_pending_questions() == ["BTC RSI 설명해줘"]
    assert handler.get_pending_questions() == []


def test_mute_and_unmute_toggle_state():
    handler = _make_handler()

    handler._handle_command("/mute")
    assert handler.muted is True

    handler._handle_command("/unmute")
    assert handler.muted is False


def test_status_report_info_and_stop_flags_can_be_reset():
    handler = _make_handler()

    handler._handle_command("/status")
    handler._handle_command("/report")
    handler._handle_command("/info")
    handler._handle_command("/criteria")
    handler._handle_command("/tuning")
    handler._handle_command("/stop")

    assert handler.status_requested is True
    assert handler.report_requested is True
    assert handler.info_requested is True
    assert handler.criteria_requested is True
    assert handler.tuning_requested is True
    assert handler.kill_switch is True

    handler.reset_status()
    handler.reset_report()
    handler.reset_info()
    handler.reset_criteria()
    handler.reset_tuning()

    assert handler.status_requested is False
    assert handler.report_requested is False
    assert handler.info_requested is False
    assert handler.criteria_requested is False
    assert handler.tuning_requested is False


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"ok": True, "result": []}

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, params))
        return self.response


def test_poll_commands_marks_success_and_uses_configured_timeout():
    handler = _make_handler()
    client = _FakeClient(_FakeResponse())
    handler._client = client
    handler._poll_timeout_seconds = 7

    assert handler.poll_commands() == []
    assert handler.last_poll_ok is True
    assert client.calls[0][1]["timeout"] == 7


def test_poll_commands_marks_failure_on_http_error():
    handler = _make_handler()
    handler._client = _FakeClient(_FakeResponse(status_code=500))

    assert handler.poll_commands() == []
    assert handler.last_poll_ok is False
