import html
import logging
import time

import httpx

from cryptolight.strategy.base import Signal

logger = logging.getLogger("cryptolight.bot.telegram")

ACTION_EMOJI = {"buy": "\U0001f7e2", "sell": "\U0001f534", "hold": "\u26aa"}
ACTION_LABEL = {"buy": "매수 시그널", "sell": "매도 시그널", "hold": "관망"}


# 알림 레벨별 허용 이벤트
_LEVEL_EVENTS: dict[str, set[str]] = {
    "silent": {"killswitch", "error"},
    "minimal": {"killswitch", "error", "execution", "stop_trigger"},
    "normal": {"killswitch", "error", "execution", "stop_trigger", "daily_summary", "startup", "shutdown", "signal", "cycle_summary"},
    "verbose": {"killswitch", "error", "execution", "stop_trigger", "daily_summary", "startup", "shutdown", "signal", "cycle_summary", "risk_blocked", "tuning", "screening"},
}


class TelegramBot:
    def __init__(self, token: str, chat_id: str, notification_level: str = "normal"):
        self._token = token
        self._chat_id = chat_id
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._client = httpx.Client(timeout=10.0)
        self._notification_level = notification_level

    def should_notify(self, event_type: str) -> bool:
        allowed = _LEVEL_EVENTS.get(self._notification_level, _LEVEL_EVENTS["normal"])
        return event_type in allowed

    def send_message(self, text: str) -> bool:
        delay_seconds = 0.5
        for attempt in range(1, 4):
            try:
                resp = self._client.post(
                    f"{self._base_url}/sendMessage",
                    json={"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"},
                )
                if resp.status_code == 200 and resp.json().get("ok"):
                    return True

                retry_after = 0.0
                if resp.status_code == 429:
                    try:
                        retry_after = float(resp.json().get("parameters", {}).get("retry_after", 0))
                    except Exception:
                        retry_after = 0.0

                if resp.status_code in {429, 500, 502, 503, 504} and attempt < 3:
                    logger.warning("텔레그램 전송 재시도(%d/3): status=%s", attempt, resp.status_code)
                    time.sleep(max(retry_after, delay_seconds))
                    delay_seconds *= 2
                    continue

                logger.warning("텔레그램 전송 실패: %s", resp.text)
                return False
            except httpx.TimeoutException as e:
                if attempt < 3:
                    logger.warning("텔레그램 전송 타임아웃 재시도(%d/3): %s", attempt, e)
                    time.sleep(delay_seconds)
                    delay_seconds *= 2
                    continue
                logger.error("텔레그램 전송 에러: %s", e)
                return False
            except httpx.RequestError as e:
                if attempt < 3:
                    logger.warning("텔레그램 전송 요청 재시도(%d/3): %s", attempt, e)
                    time.sleep(delay_seconds)
                    delay_seconds *= 2
                    continue
                logger.error("텔레그램 전송 에러: %s", e)
                return False
            except Exception as e:
                logger.error("텔레그램 전송 에러: %s", e)
                return False

        return False

    def send_signal(self, signal: Signal, price: float | None = None) -> bool:
        emoji = ACTION_EMOJI.get(signal.action, "")
        label = ACTION_LABEL.get(signal.action, signal.action)

        lines = [f"{emoji} <b>{label}</b>", f"종목: {signal.symbol}"]

        if price is not None:
            lines.append(f"현재가: {price:,.0f} KRW")

        lines.append(f"사유: {html.escape(signal.reason)}")

        if signal.confidence > 0:
            lines.append(f"신뢰도: {signal.confidence:.0%}")

        if signal.indicators:
            indicator_parts = [f"{k}={v}" for k, v in signal.indicators.items() if v is not None]
            if indicator_parts:
                lines.append(f"지표: {html.escape(', '.join(indicator_parts))}")

        return self.send_message("\n".join(lines))

    def send_startup(self, symbols: list[str], mode: str):
        self.send_message(
            f"\U0001f680 <b>cryptolight 시작</b>\n"
            f"모드: {mode}\n"
            f"종목: {', '.join(symbols)}"
        )

    def send_daily_summary(self, pnl_data: dict, positions_summary: str = "", trades: list | None = None, holdings: list | None = None, cash_krw: float = 0):
        trade_count = pnl_data.get("trade_count", 0)
        total_bought = pnl_data.get("total_bought", 0)
        total_sold = pnl_data.get("total_sold", 0)
        total_commission = pnl_data.get("total_commission", 0)
        realized_pnl = pnl_data.get("realized_pnl", 0)

        lines = ["\U0001f4ca <b>일일 요약</b>"]

        if trade_count == 0:
            lines.append("거래 없음")
        else:
            lines.append(f"거래 {trade_count}건")
            if total_bought > 0:
                lines.append(f"  \U0001f7e2 매수: {total_bought:,.0f} KRW")
            if total_sold > 0:
                lines.append(f"  \U0001f534 매도: {total_sold:,.0f} KRW")
            lines.append(f"  수수료: {total_commission:,.0f} KRW")

        if trades:
            lines.append("\n\U0001f4dd <b>거래 내역</b>")
            for t in reversed(trades):
                coin = t.symbol.split("-")[1] if "-" in t.symbol else t.symbol
                time_str = t.timestamp[11:16] if len(t.timestamp) > 16 else ""
                qty_str = f"{t.quantity:.8f}".rstrip("0").rstrip(".")
                if t.side == "buy":
                    lines.append(
                        f"  \U0001f7e2 {time_str} <b>{coin}</b> {t.amount_krw:,.0f}원 / {qty_str}개 / @{t.price:,.0f}원"
                    )
                else:
                    lines.append(
                        f"  \U0001f534 {time_str} <b>{coin}</b> {qty_str}개 → {t.amount_krw:,.0f}원 / @{t.price:,.0f}원"
                    )
                if t.reason:
                    lines.append(f"    사유: {html.escape(t.reason)}")

        if trade_count > 0:
            pnl_emoji = "\U0001f4b0" if realized_pnl >= 0 else "\U0001f4b8"
            lines.append(f"\n{pnl_emoji} <b>실현 손익: {realized_pnl:+,.0f} KRW</b>")

        if holdings or cash_krw > 0:
            lines.append("\n\U0001f4bc <b>보유 현황</b>")
            lines.append(f"  현금: {cash_krw:,.0f} KRW")

            if holdings:
                total_eval = 0.0
                total_cost = 0.0
                for h in holdings:
                    pnl = h["pnl"]
                    pnl_pct = ((h["current_price"] - h["avg_price"]) / h["avg_price"] * 100) if h["avg_price"] > 0 else 0
                    pnl_emoji = "\U0001f4c8" if pnl >= 0 else "\U0001f4c9"
                    qty_str = f"{h['quantity']:.8f}".rstrip("0").rstrip(".")
                    lines.append(
                        f"  {pnl_emoji} <b>{h['coin']}</b> {qty_str}개 | @{h['avg_price']:,.0f} → {h['current_price']:,.0f}원 | {pnl:+,.0f}원 ({pnl_pct:+.1f}%)"
                    )
                    total_eval += h["eval_amount"]
                    total_cost += h["cost"]

                total_asset = cash_krw + total_eval
                total_pnl = total_eval - total_cost
                lines.append(f"\n  <b>총 자산: {total_asset:,.0f} KRW</b>")
                if total_eval > 0:
                    lines.append(f"  코인 평가손익: {total_pnl:+,.0f}원")
            elif cash_krw > 0:
                lines.append(f"\n  <b>총 자산: {cash_krw:,.0f} KRW</b>")

        self.send_message("\n".join(lines))

    def send_surge_alert(self, symbol: str, price: float, change_rate: float):
        emoji = "\U0001f4c8" if change_rate > 0 else "\U0001f4c9"
        direction = "급등" if change_rate > 0 else "급락"
        self.send_message(
            f"{emoji} <b>{direction} 알림</b>\n"
            f"종목: {symbol}\n"
            f"현재가: {price:,.0f} KRW\n"
            f"변동률: {change_rate * 100:+.2f}%"
        )

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
