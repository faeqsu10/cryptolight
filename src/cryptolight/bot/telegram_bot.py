import html
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

    def send_daily_summary(self, pnl_data: dict, positions_summary: str = ""):
        trade_count = pnl_data.get("trade_count", 0)
        total_bought = pnl_data.get("total_bought", 0)
        total_sold = pnl_data.get("total_sold", 0)
        total_commission = pnl_data.get("total_commission", 0)
        realized_pnl = pnl_data.get("realized_pnl", 0)

        lines = ["\U0001f4ca <b>일일 요약</b>"]

        # 거래 활동 해설
        if trade_count == 0:
            lines.append("오늘은 거래가 없었습니다.")
        else:
            lines.append(f"오늘 총 {trade_count}건의 거래가 있었습니다.")
            if total_bought > 0:
                lines.append(f"  \U0001f7e2 매수: {total_bought:,.0f} KRW (코인 구매에 사용한 금액)")
            if total_sold > 0:
                lines.append(f"  \U0001f534 매도: {total_sold:,.0f} KRW (코인 판매로 받은 금액)")
            lines.append(f"  수수료: {total_commission:,.0f} KRW")

        # 실현 손익 해설
        if trade_count > 0:
            pnl_emoji = "\U0001f4b0" if realized_pnl >= 0 else "\U0001f4b8"
            lines.append(f"\n{pnl_emoji} <b>실현 손익: {realized_pnl:+,.0f} KRW</b>")
            if total_sold == 0 and total_bought > 0:
                lines.append("  (매수만 있어 아직 확정 수익 없음 — 수수료만 차감)")
            elif realized_pnl > 0:
                lines.append("  (매도 금액이 매수 금액보다 커서 수익 실현!)")
            elif realized_pnl < 0:
                lines.append("  (매도 금액이 매수 금액보다 작아 손실 발생)")
            else:
                lines.append("  (본전 수준)")

        # 포지션 요약
        if positions_summary:
            lines.append("\n\U0001f4bc <b>보유 현황</b>")
            lines.append(f"<pre>{html.escape(positions_summary)}</pre>")

            # 총 손익 해설
            if "손익:" in positions_summary:
                if "-" in positions_summary.split("손익:")[1].split("\n")[0]:
                    lines.append("\n총 자산이 초기 투자금보다 적습니다. 보유 코인의 가격이 회복되면 개선될 수 있습니다.")
                elif "+" in positions_summary.split("손익:")[1].split("\n")[0]:
                    lines.append("\n총 자산이 초기 투자금보다 많습니다. 잘 운영되고 있습니다!")

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
