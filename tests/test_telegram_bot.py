import httpx

from cryptolight.bot.telegram_bot import TelegramBot


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {"ok": True}
        self.text = text

    def json(self):
        return self._payload


class _RetryClient:
    def __init__(self):
        self.attempts = 0

    def post(self, *_args, **_kwargs):
        self.attempts += 1
        if self.attempts < 3:
            raise httpx.TimeoutException("timeout")
        return _FakeResponse()

    def close(self):
        return None


def test_normal_level_includes_signal_tracking():
    bot = TelegramBot("token", "123", notification_level="normal")
    try:
        assert bot.should_notify("signal") is True
        assert bot.should_notify("cycle_summary") is True
    finally:
        bot.close()


def test_send_message_retries_on_timeout(monkeypatch):
    bot = TelegramBot("token", "123")
    retry_client = _RetryClient()
    bot._client = retry_client
    monkeypatch.setattr("cryptolight.bot.telegram_bot.time.sleep", lambda _seconds: None)

    try:
        assert bot.send_message("hello") is True
        assert retry_client.attempts == 3
    finally:
        bot.close()
