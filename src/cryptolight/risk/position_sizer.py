"""포지션 사이징 — 고정금액 / 자산비율 / Kelly Criterion"""

import logging

logger = logging.getLogger("cryptolight.risk.sizer")


class PositionSizer:
    """주문 금액을 동적으로 결정한다."""

    def __init__(
        self,
        method: str = "fixed",
        fixed_amount: float = 50_000,
        risk_pct: float = 2.0,
        kelly_win_rate: float = 0.5,
        kelly_avg_win: float = 1.0,
        kelly_avg_loss: float = 1.0,
        kelly_fraction: float = 0.25,
        max_amount: float = 500_000,
    ):
        """
        Args:
            method: "fixed" | "percent" | "kelly"
            fixed_amount: fixed 모드 주문 금액
            risk_pct: percent 모드 — 총자산의 N%
            kelly_win_rate: kelly 모드 — 승률 (0~1)
            kelly_avg_win: kelly 모드 — 평균 수익 비율
            kelly_avg_loss: kelly 모드 — 평균 손실 비율
            kelly_fraction: kelly 결과에 곱하는 안전 계수 (1/4 Kelly 기본)
            max_amount: 최대 주문 금액
        """
        self.method = method
        self.fixed_amount = fixed_amount
        self.risk_pct = risk_pct
        self.kelly_win_rate = kelly_win_rate
        self.kelly_avg_win = kelly_avg_win
        self.kelly_avg_loss = kelly_avg_loss
        self.kelly_fraction = kelly_fraction
        self.max_amount = max_amount

    def calculate(self, equity: float, confidence: float = 1.0) -> float:
        """현재 자산과 시그널 신뢰도로 주문 금액을 계산한다."""
        if self.method == "percent":
            amount = equity * (self.risk_pct / 100) * confidence
        elif self.method == "kelly":
            amount = equity * self._kelly_fraction() * confidence
        else:
            amount = self.fixed_amount * confidence

        amount = max(5_000, min(amount, self.max_amount))  # 최소 5천원
        logger.debug(
            "포지션 사이징 [%s]: equity=%s, confidence=%.2f → %s KRW",
            self.method, f"{equity:,.0f}", confidence, f"{amount:,.0f}",
        )
        return round(amount, 0)

    def _kelly_fraction(self) -> float:
        """Kelly Criterion: f* = (p*b - q) / b"""
        p = self.kelly_win_rate
        q = 1 - p
        b = self.kelly_avg_win / self.kelly_avg_loss if self.kelly_avg_loss > 0 else 1.0

        kelly = (p * b - q) / b if b > 0 else 0
        kelly = max(0, kelly)  # 음수면 배팅하지 않음
        return kelly * self.kelly_fraction

    def update_kelly_stats(self, win_rate: float, avg_win: float, avg_loss: float):
        """백테스트/실거래 결과로 Kelly 파라미터를 갱신한다."""
        self.kelly_win_rate = max(0.0, min(1.0, win_rate))
        self.kelly_avg_win = max(0.001, avg_win)
        self.kelly_avg_loss = max(0.001, avg_loss)
        logger.info(
            "Kelly 파라미터 갱신: 승률=%.1f%%, 평균수익=%.2f, 평균손실=%.2f",
            win_rate * 100, avg_win, avg_loss,
        )
