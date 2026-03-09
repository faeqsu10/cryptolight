import logging

import httpx

from cryptolight.strategy.base import Signal

logger = logging.getLogger("cryptolight.bot.telegram")

ACTION_EMOJI = {"buy": "\U0001f7e2", "sell": "\U0001f534", "hold": "\u26aa"}
ACTION_LABEL = {"buy": "매수 시그널", "sell": "매도 시그널", "hold": "관망"}


class TelegramBot:
    def __init__(self, token: str, chat_id: str):
        self._token = token
        self._chat_id = chat_id
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._client = httpx.Client(timeout=10.0)

    def send_message(self, text: str) -> bool:
        try:
            resp = self._client.post(
                f"{self._base_url}/sendMessage",
                json={"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"},
            )
            if resp.status_code == 200 and resp.json().get("ok"):
                return True
            logger.warning("텔레그램 전송 실패: %s", resp.text)
            return False
        except Exception as e:
            logger.error("텔레그램 전송 에러: %s", e)
            return False

    def send_signal(self, signal: Signal, price: float | None = None) -> bool:
        emoji = ACTION_EMOJI.get(signal.action, "")
        label = ACTION_LABEL.get(signal.action, signal.action)

        lines = [f"{emoji} <b>{label}</b>", f"종목: {signal.symbol}"]

        if price is not None:
            lines.append(f"현재가: {price:,.0f} KRW")

        lines.append(f"사유: {signal.reason}")

        if signal.confidence > 0:
            lines.append(f"신뢰도: {signal.confidence:.0%}")

        if signal.indicators:
            indicator_parts = [f"{k}={v}" for k, v in signal.indicators.items() if v is not None]
            if indicator_parts:
                lines.append(f"지표: {', '.join(indicator_parts)}")

        return self.send_message("\n".join(lines))

    def send_startup(self, symbols: list[str], mode: str):
        self.send_message(
            f"\U0001f680 <b>cryptolight 시작</b>\n"
            f"모드: {mode}\n"
            f"종목: {', '.join(symbols)}"
        )

    def send_daily_summary(self, summary: dict):
        lines = ["\U0001f4ca <b>일일 요약</b>"]
        for key, value in summary.items():
            lines.append(f"  {key}: {value}")
        self.send_message("\n".join(lines))

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
