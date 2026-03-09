"""텔레그램 명령어 처리 — 상태 조회, 긴급 정지"""

import logging

import httpx

logger = logging.getLogger("cryptolight.bot.command")


class CommandHandler:
    """텔레그램 업데이트를 폴링하여 명령어를 처리한다."""

    def __init__(self, token: str, chat_id: str):
        self._token = token
        self._chat_id = chat_id
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._client = httpx.Client(timeout=10.0)
        self._last_update_id = 0
        self._kill_switch = False
        self._report_requested = False

    @property
    def kill_switch(self) -> bool:
        return self._kill_switch

    @property
    def report_requested(self) -> bool:
        return self._report_requested

    def reset_report(self):
        self._report_requested = False

    def poll_commands(self) -> list[str]:
        """새 명령어를 폴링한다. 명령어 목록 반환."""
        commands = []
        try:
            resp = self._client.get(
                f"{self._base_url}/getUpdates",
                params={"offset": self._last_update_id + 1, "timeout": 1},
            )
            if resp.status_code != 200:
                return commands

            data = resp.json()
            if not data.get("ok"):
                return commands

            for update in data.get("result", []):
                self._last_update_id = update["update_id"]
                message = update.get("message", {})

                # 본인 채팅방에서 온 메시지만 처리
                if str(message.get("chat", {}).get("id")) != self._chat_id:
                    continue

                text = message.get("text", "").strip()
                if text.startswith("/"):
                    cmd = text.split()[0].lower()
                    commands.append(cmd)
                    self._handle_command(cmd)

        except Exception:
            logger.exception("명령어 폴링 실패")

        return commands

    def _handle_command(self, cmd: str):
        if cmd == "/stop":
            self._kill_switch = True
            self._send("거래 중지 명령 수신. 봇을 정지합니다.")
            logger.warning("킬스위치 활성화: /stop 명령")
        elif cmd == "/status":
            self._send("상태 조회는 다음 실행 주기에 응답합니다.")
        elif cmd == "/report":
            self._report_requested = True
            self._send("일일 요약을 생성 중입니다...")
        elif cmd == "/help":
            self._send(
                "<b>명령어 목록</b>\n"
                "/status — 현재 상태 조회\n"
                "/report — 일일 요약 리포트\n"
                "/stop — 긴급 거래 중지\n"
                "/help — 도움말"
            )
        else:
            self._send(f"알 수 없는 명령어: {cmd}\n/help 로 목록을 확인하세요.")

    def _send(self, text: str):
        try:
            self._client.post(
                f"{self._base_url}/sendMessage",
                json={"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"},
            )
        except Exception:
            logger.exception("명령어 응답 전송 실패")

    def close(self):
        self._client.close()
