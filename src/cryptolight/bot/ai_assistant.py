"""Gemini AI 어시스턴트 — 텔레그램 /ask 명령어용"""

import html as html_mod
import logging
import re
from datetime import date

import httpx

logger = logging.getLogger("cryptolight.bot.ai_assistant")

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

SYSTEM_PROMPT = (
    "당신은 암호화폐 트레이딩 전문 어시스턴트입니다. "
    "cryptolight 자동매매봇의 사용자에게 시장 분석, 전략, 리스크 관리에 대해 "
    "간결하고 실용적인 답변을 제공합니다. "
    "답변은 텔레그램 메시지에 적합하게 짧고 명확하게 작성합니다. "
    "투자 조언이 아닌 정보 제공임을 유의합니다."
)


def markdown_to_telegram_html(text: str) -> str:
    """마크다운 텍스트를 텔레그램 HTML로 변환한다."""
    # 먼저 HTML 특수문자 이스케이프
    text = html_mod.escape(text)
    # **bold** → <b>bold</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # *italic* → <i>italic</i> (볼드 변환 후 처리)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    # `code` → <code>code</code>
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


class AIAssistant:
    """Gemini API를 사용한 질문 응답. 일일 사용 제한 포함."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", daily_limit: int = 10):
        self._api_key = api_key
        self._model = model
        self._daily_limit = daily_limit
        self._usage_date: date | None = None
        self._usage_count: int = 0
        self._client = httpx.Client(timeout=30.0)

    def ask(self, question: str, context: str = "") -> str:
        """질문에 답변한다. 일일 제한 초과 시 안내 메시지 반환."""
        if not self._api_key:
            return "Google API 키가 설정되지 않았습니다."

        # 일일 제한 체크
        today = date.today()
        if self._usage_date != today:
            self._usage_date = today
            self._usage_count = 0

        if self._usage_count >= self._daily_limit:
            return f"일일 사용 제한({self._daily_limit}회)에 도달했습니다. 내일 다시 이용해주세요."

        # 컨텍스트 포함 프롬프트 구성
        user_content = question
        if context:
            user_content = f"[현재 시장 상태]\n{context}\n\n[질문]\n{question}"

        try:
            resp = self._client.post(
                f"{GEMINI_API_BASE}/{self._model}:generateContent",
                params={"key": self._api_key},
                json={
                    "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                    "contents": [{"parts": [{"text": user_content}]}],
                    "generationConfig": {
                        "maxOutputTokens": 2048,
                        "temperature": 0.7,
                    },
                },
            )

            if resp.status_code != 200:
                logger.warning("Gemini API 에러: %d %s", resp.status_code, resp.text[:200])
                return f"AI 응답 실패 (HTTP {resp.status_code})"

            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return "AI가 답변을 생성하지 못했습니다."

            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            if not text:
                return "AI가 빈 응답을 반환했습니다."

            self._usage_count += 1
            remaining = self._daily_limit - self._usage_count
            logger.info("/ask 사용: %d/%d (남은 횟수: %d)", self._usage_count, self._daily_limit, remaining)

            return text.strip()

        except httpx.TimeoutException:
            return "AI 응답 시간 초과. 잠시 후 다시 시도해주세요."
        except Exception as e:
            logger.exception("AI 어시스턴트 에러")
            return f"AI 에러: {e}"

    @property
    def remaining_today(self) -> int:
        today = date.today()
        if self._usage_date != today:
            return self._daily_limit
        return max(0, self._daily_limit - self._usage_count)

    def close(self):
        self._client.close()
