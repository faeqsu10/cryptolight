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

    def send_daily_summary(self, pnl_data: dict, positions_summary: str = "", trades: list | None = None, holdings: list | None = None, cash_krw: float = 0):
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
                lines.append(f"  \U0001f7e2 매수(구매): {total_bought:,.0f} KRW")
            if total_sold > 0:
                lines.append(f"  \U0001f534 매도(판매): {total_sold:,.0f} KRW")
            lines.append(f"  수수료: {total_commission:,.0f} KRW")

        # 거래 상세 내역
        if trades:
            lines.append("\n\U0001f4dd <b>거래 내역</b>")
            for t in reversed(trades):  # 시간순 정렬
                coin = t.symbol.split("-")[1] if "-" in t.symbol else t.symbol
                time_str = t.timestamp[11:16] if len(t.timestamp) > 16 else ""
                qty_str = f"{t.quantity:.8f}".rstrip("0").rstrip(".")
                if t.side == "buy":
                    lines.append(
                        f"  \U0001f7e2 {time_str} <b>{coin}</b> 매수\n"
                        f"    {t.amount_krw:,.0f}원으로 {qty_str}개 구매 (개당 {t.price:,.0f}원)"
                    )
                else:
                    lines.append(
                        f"  \U0001f534 {time_str} <b>{coin}</b> 매도\n"
                        f"    {qty_str}개 판매 → {t.amount_krw:,.0f}원 수령 (개당 {t.price:,.0f}원)"
                    )
                if t.reason:
                    lines.append(f"    사유: {html.escape(t.reason)}")

        # 용어 안내
        if trade_count > 0:
            lines.append(
                "\n<i>매수 = 코인을 원화로 사는 것\n"
                "매도 = 보유 코인을 팔아 원화로 바꾸는 것\n"
                "수수료 = 거래소에 내는 거래 비용 (0.05%)</i>"
            )

        # 실현 손익 해설
        if trade_count > 0:
            pnl_emoji = "\U0001f4b0" if realized_pnl >= 0 else "\U0001f4b8"
            lines.append(f"\n{pnl_emoji} <b>실현 손익: {realized_pnl:+,.0f} KRW</b>")
            if total_sold == 0 and total_bought > 0:
                lines.append("  아직 팔지 않아서 확정 수익은 없습니다 (수수료만 차감)")
            elif realized_pnl > 0:
                lines.append("  판 금액이 산 금액보다 커서 수익이 났습니다!")
            elif realized_pnl < 0:
                lines.append("  판 금액이 산 금액보다 작아 손실이 발생했습니다")
            else:
                lines.append("  본전 수준입니다")

        # 보유 현황 (초보자 친화)
        if holdings or cash_krw > 0:
            lines.append("\n\U0001f4bc <b>현재 보유 현황</b>")
            lines.append(f"  현금: {cash_krw:,.0f} KRW (언제든 사용 가능한 원화)")

            if holdings:
                total_eval = 0.0
                total_cost = 0.0
                for h in holdings:
                    pnl = h["pnl"]
                    pnl_pct = ((h["current_price"] - h["avg_price"]) / h["avg_price"] * 100) if h["avg_price"] > 0 else 0
                    pnl_emoji = "\U0001f4c8" if pnl >= 0 else "\U0001f4c9"
                    qty_str = f"{h['quantity']:.8f}".rstrip("0").rstrip(".")
                    lines.append(
                        f"\n  {pnl_emoji} <b>{h['coin']}</b> ({h['symbol']})\n"
                        f"    보유수량: {qty_str}개\n"
                        f"    매수가: {h['avg_price']:,.0f}원 (살 때 가격)\n"
                        f"    현재가: {h['current_price']:,.0f}원\n"
                        f"    평가금액: {h['eval_amount']:,.0f}원\n"
                        f"    손익: {pnl:+,.0f}원 ({pnl_pct:+.1f}%)"
                    )
                    total_eval += h["eval_amount"]
                    total_cost += h["cost"]

                total_asset = cash_krw + total_eval
                lines.append(f"\n  <b>총 자산: {total_asset:,.0f} KRW</b>")
                if total_eval > 0:
                    total_pnl = total_eval - total_cost
                    if total_pnl >= 0:
                        lines.append(f"  코인 평가수익: +{total_pnl:,.0f}원 (아직 안 팔아서 확정은 아님)")
                    else:
                        lines.append(f"  코인 평가손실: {total_pnl:,.0f}원 (팔지 않으면 확정 손실 아님)")
            elif cash_krw > 0:
                lines.append("\n  현재 보유 코인 없음 — 전액 현금 상태")
                lines.append(f"  <b>총 자산: {cash_krw:,.0f} KRW</b>")

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
