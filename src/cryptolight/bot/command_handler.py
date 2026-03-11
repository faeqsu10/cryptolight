"""텔레그램 명령어 처리 — 상태 조회, 긴급 정지"""

import logging
import threading

import httpx

logger = logging.getLogger("cryptolight.bot.command")


class CommandHandler:
    """텔레그램 업데이트를 폴링하여 명령어를 처리한다."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        poll_timeout_seconds: int = 20,
        request_timeout_seconds: int = 30,
    ):
        self._token = token
        self._chat_id = chat_id
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._poll_timeout_seconds = poll_timeout_seconds
        self._client = httpx.Client(timeout=float(request_timeout_seconds))
        self._lock = threading.Lock()
        self._last_update_id = 0
        self._last_poll_ok = True
        self._kill_switch = False
        self._report_requested = False
        self._status_requested = False
        self._info_requested = False
        self._criteria_requested = False
        self._tuning_requested = False
        self._ask_queue: list[str] = []
        self._muted = False
        self._flush_old_updates()

    @property
    def kill_switch(self) -> bool:
        with self._lock:
            return self._kill_switch

    @property
    def report_requested(self) -> bool:
        with self._lock:
            return self._report_requested

    @property
    def status_requested(self) -> bool:
        with self._lock:
            return self._status_requested

    @property
    def info_requested(self) -> bool:
        with self._lock:
            return self._info_requested

    @property
    def muted(self) -> bool:
        with self._lock:
            return self._muted

    @property
    def criteria_requested(self) -> bool:
        with self._lock:
            return self._criteria_requested

    @property
    def tuning_requested(self) -> bool:
        with self._lock:
            return self._tuning_requested

    @property
    def last_poll_ok(self) -> bool:
        with self._lock:
            return self._last_poll_ok

    def reset_report(self):
        with self._lock:
            self._report_requested = False

    def reset_status(self):
        with self._lock:
            self._status_requested = False

    def reset_info(self):
        with self._lock:
            self._info_requested = False

    def reset_criteria(self):
        with self._lock:
            self._criteria_requested = False

    def reset_tuning(self):
        with self._lock:
            self._tuning_requested = False

    def _flush_old_updates(self):
        """시작 시 밀려있던 옛 업데이트를 건너뛴다."""
        try:
            resp = self._client.get(
                f"{self._base_url}/getUpdates",
                params={"offset": -1, "timeout": 0},
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("result", [])
                if results:
                    self._last_update_id = results[-1]["update_id"]
                    logger.info("이전 업데이트 %d건 건너뜀 (마지막 ID: %d)", len(results), self._last_update_id)
        except Exception:
            logger.debug("이전 업데이트 flush 실패 — 무시")

    def poll_commands(self) -> list[str]:
        """새 명령어를 폴링한다. 명령어 목록 반환."""
        commands = []
        try:
            resp = self._client.get(
                f"{self._base_url}/getUpdates",
                params={"offset": self._last_update_id + 1, "timeout": self._poll_timeout_seconds},
            )
            if resp.status_code != 200:
                with self._lock:
                    self._last_poll_ok = False
                return commands

            data = resp.json()
            if not data.get("ok"):
                with self._lock:
                    self._last_poll_ok = False
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
                    self._handle_command(cmd, text)

            with self._lock:
                self._last_poll_ok = True

        except Exception:
            with self._lock:
                self._last_poll_ok = False
            logger.exception("명령어 폴링 실패")

        return commands

    def get_pending_questions(self) -> list[str]:
        """대기 중인 /ask 질문들을 가져오고 큐를 비운다."""
        with self._lock:
            questions = list(self._ask_queue)
            self._ask_queue.clear()
        return questions

    def _handle_command(self, cmd: str, full_text: str = ""):
        if cmd == "/ask":
            question = full_text[len("/ask"):].strip() if full_text else ""
            if not question:
                self._send("사용법: /ask 질문내용\n예: /ask BTC RSI가 30 이하일 때 매수 전략은?")
            else:
                with self._lock:
                    self._ask_queue.append(question)
                self._send("AI에게 질문 중...")
            return
        if cmd == "/stop":
            with self._lock:
                self._kill_switch = True
            self._send("거래 중지 명령 수신. 봇을 정지합니다.")
            logger.warning("킬스위치 활성화: /stop 명령")
        elif cmd == "/status":
            with self._lock:
                self._status_requested = True
            self._send("상태 조회 중...")
        elif cmd == "/report":
            with self._lock:
                self._report_requested = True
            self._send("일일 요약을 생성 중입니다...")
        elif cmd == "/info":
            with self._lock:
                self._info_requested = True
            self._send("시장 상태를 조회 중입니다...")
        elif cmd == "/criteria":
            with self._lock:
                self._criteria_requested = True
            self._send("현재 매수/매도 기준을 정리 중입니다...")
        elif cmd == "/tuning":
            with self._lock:
                self._tuning_requested = True
            self._send("최근 자동 조정 이력을 정리 중입니다...")
        elif cmd == "/mute":
            with self._lock:
                self._muted = True
            self._send("🔇 알림이 꺼졌습니다. 자동 알림(시그널, 급등/급락)이 중지됩니다.\n명령어 응답은 정상 작동합니다.\n/unmute 로 다시 켤 수 있습니다.")
            logger.info("알림 음소거 활성화")
        elif cmd == "/unmute":
            with self._lock:
                self._muted = False
            self._send("🔔 알림이 켜졌습니다. 자동 알림이 다시 전송됩니다.")
            logger.info("알림 음소거 해제")
        elif cmd == "/help":
            with self._lock:
                muted = self._muted
            mute_status = "🔇 꺼짐" if muted else "🔔 켜짐"
            self._send(
                "<b>명령어 목록</b>\n"
                "/info — 시장 상태 (RSI, 국면, 매수/매도 조건)\n"
                "/ask — AI에게 질문하기\n"
                "/status — 봇 상태 조회\n"
                "/report — 일일 요약 리포트\n"
                "/criteria — 현재 매수/매도 기준 설명\n"
                "/tuning — 최근 자동 조정 이력 조회\n"
                "/mute — 자동 알림 끄기\n"
                "/unmute — 자동 알림 켜기\n"
                "/stop — 긴급 거래 중지\n"
                "/help — 도움말\n"
                f"\n현재 알림: {mute_status}"
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
