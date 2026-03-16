"""Command polling loop extracted from the main runtime entrypoint."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable


def command_loop(
    cmd_handler,
    scheduler,
    bot,
    *,
    logger: logging.Logger,
    broker=None,
    repo=None,
    client=None,
    symbols: list[str] | None = None,
    settings=None,
    stop_event: threading.Event | None = None,
    daily_summary_job: Callable[..., None],
    health=None,
    get_runtime_state: Callable[[Any], dict],
    send_market_info: Callable[..., None],
    send_strategy_criteria: Callable[..., None],
    send_tuning_history: Callable[..., None],
    ai_assistant=None,
    build_market_context: Callable[[], str] | None = None,
    markdown_to_telegram_html: Callable[[str], str] | None = None,
) -> None:
    """Long-poll Telegram commands and dispatch runtime actions."""

    logger.info("명령어 폴링 스레드 시작 (long polling)")
    consecutive_failures = 0
    backoff_initial = max(0.1, float(getattr(settings, "telegram_poll_backoff_initial_seconds", 1.0)))
    backoff_max = max(backoff_initial, float(getattr(settings, "telegram_poll_backoff_max_seconds", 30.0)))

    while not (stop_event and stop_event.is_set()):
        try:
            cmd_handler.poll_commands()
            if not cmd_handler.last_poll_ok:
                consecutive_failures += 1
                sleep_seconds = min(backoff_max, backoff_initial * (2 ** (consecutive_failures - 1)))
                logger.warning(
                    "명령어 폴링 실패: %d회 연속, %.1fs 후 재시도",
                    consecutive_failures,
                    sleep_seconds,
                )
                time.sleep(sleep_seconds)
                continue

            consecutive_failures = 0
            if cmd_handler.kill_switch:
                logger.warning("킬스위치 활성 — 스케줄러 종료 요청")
                if bot:
                    bot.send_message("\u26d4 킬스위치 활성 — 봇을 종료합니다.")
                scheduler.shutdown(wait=False)
                break

            if cmd_handler.report_requested and bot and repo and client and symbols:
                daily_summary_job(bot, broker, repo, client, symbols)
                cmd_handler.reset_report()

            if cmd_handler.status_requested and bot:
                status_text = health.summary_text(schedule_interval_minutes=settings.schedule_interval_minutes) if health else "헬스 모니터 미초기화"
                runtime_state = get_runtime_state(settings)
                status_text += (
                    f"\n전략: {runtime_state['strategy_name']}\n"
                    f"종목: {', '.join(runtime_state['symbol_list'])}"
                )
                bot.send_message(f"\U0001f4cb <b>봇 상태</b>\n<pre>{status_text}</pre>")
                cmd_handler.reset_status()

            if cmd_handler.info_requested and bot and settings:
                send_market_info(bot, settings)
                cmd_handler.reset_info()

            if cmd_handler.criteria_requested and bot and settings:
                send_strategy_criteria(bot, settings)
                cmd_handler.reset_criteria()

            if cmd_handler.tuning_requested and bot and repo and settings:
                send_tuning_history(bot, repo, settings)
                cmd_handler.reset_tuning()

            if ai_assistant and bot and build_market_context and markdown_to_telegram_html:
                for question in cmd_handler.get_pending_questions():
                    context = build_market_context()
                    answer = ai_assistant.ask(question, context=context)
                    remaining = ai_assistant.remaining_today
                    bot.send_message(
                        f"\U0001f916 <b>AI 답변</b>\n\n"
                        f"{markdown_to_telegram_html(answer)}\n\n"
                        f"<i>남은 횟수: {remaining}회/일</i>"
                    )
        except Exception:
            logger.exception("명령어 폴링 중 에러 발생")
