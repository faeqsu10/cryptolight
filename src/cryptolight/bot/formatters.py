"""텔레그램 메시지용 포매팅 유틸리티 — main.py에서 분리."""

from zoneinfo import ZoneInfo


def explain_indicators(indicators: dict) -> str:
    """지표값을 초보자 친화적 해설로 변환한다."""
    lines = []
    rsi = indicators.get("rsi")
    if rsi is not None:
        if rsi <= 30:
            desc = "과매도 — 많이 떨어져서 반등 가능성"
        elif rsi <= 40:
            desc = "약간 저평가 — 살 만한 구간"
        elif rsi >= 70:
            desc = "과매수 — 많이 올라서 하락 주의"
        elif rsi >= 60:
            desc = "약간 고평가 — 추가 매수 주의"
        else:
            desc = "중립 — 뚜렷한 방향 없음"
        lines.append(f"  RSI {rsi:.1f}: {desc}")

    macd = indicators.get("macd")
    macd_signal = indicators.get("macd_signal")
    if macd is not None and macd_signal is not None:
        if macd > macd_signal:
            desc = "상승 추세 — 매수 힘이 강함"
        else:
            desc = "하락 추세 — 매도 힘이 강함"
        lines.append(f"  MACD: {desc}")

    pct_b = indicators.get("pct_b")
    if pct_b is not None:
        if pct_b <= 0.2:
            desc = "밴드 하단 — 저점 근처"
        elif pct_b >= 0.8:
            desc = "밴드 상단 — 고점 근처"
        else:
            desc = "밴드 중간 — 보통 구간"
        lines.append(f"  볼린저: {desc}")

    return "\n".join(lines)


def format_param_value(value) -> str:
    if value is None:
        return "기본값"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}"
    return str(value)


def format_datetime_for_user(dt, timezone_name: str) -> str:
    if not dt:
        return "알 수 없음"
    try:
        tz = ZoneInfo(timezone_name)
        if getattr(dt, "tzinfo", None) is None:
            dt = dt.replace(tzinfo=tz)
        else:
            dt = dt.astimezone(tz)
        return dt.strftime("%Y-%m-%d %H:%M %Z")
    except Exception:
        return str(dt)


def format_remaining_time(seconds: float) -> str:
    if seconds <= 0:
        return "없음"
    total_minutes = int(seconds // 60)
    hours, minutes = divmod(total_minutes, 60)
    if hours > 0:
        return f"{hours}시간 {minutes}분"
    return f"{minutes}분"


def parameter_label(strategy_name: str, parameter: str) -> str:
    labels = {
        "period": "기간",
        "oversold": "RSI 과매도 기준",
        "overbought": "RSI 과매수 기준",
        "fast": "MACD 빠른선 기간",
        "slow": "MACD 느린선 기간",
        "signal_period": "MACD 시그널 기간",
        "std_mult": "볼린저 표준편차 배수",
        "k": "변동성 돌파 k값",
        "rsi_period": "RSI 기간",
        "rsi_oversold": "RSI 과매도 기준",
        "rsi_overbought": "RSI 과매수 기준",
        "macd_fast": "MACD 빠른선 기간",
        "macd_slow": "MACD 느린선 기간",
        "macd_signal": "MACD 시그널 기간",
        "bb_period": "볼린저 기간",
        "bb_std_mult": "볼린저 표준편차 배수",
        "volume_period": "거래량 평균 기간",
    }
    return labels.get(parameter, f"{strategy_name}.{parameter}")


def parameter_change_explainer(strategy_name: str, parameter: str, old_value, new_value) -> str:
    if old_value == new_value:
        return "변경 없음"

    lowered = old_value is not None and new_value < old_value
    raised = old_value is not None and new_value > old_value

    if parameter in {"oversold", "rsi_oversold"}:
        if lowered:
            return "더 많이 눌렸을 때만 매수하게 되어, 급한 진입을 줄이는 보수적 조정입니다"
        if raised:
            return "조금만 눌려도 매수 후보가 되어, 더 빠르게 진입하는 공격적 조정입니다"
    if parameter in {"overbought", "rsi_overbought"}:
        if lowered:
            return "조금만 과열돼도 매도 후보가 되어, 이익 보호를 더 빠르게 시도합니다"
        if raised:
            return "더 크게 오른 뒤에야 매도하게 되어, 추세를 오래 따라가려는 조정입니다"
    if parameter in {"fast", "macd_fast", "signal_period", "macd_signal"}:
        if lowered:
            return "추세 변화에 더 민감해져 신호가 빨라지지만, 잡음도 늘 수 있습니다"
        if raised:
            return "신호가 조금 느려지지만, 잦은 흔들림을 덜 따라가게 됩니다"
    if parameter in {"slow", "macd_slow"}:
        if lowered:
            return "더 짧은 중기 흐름을 반영해 방향 전환을 빨리 감지합니다"
        if raised:
            return "더 큰 흐름 위주로 판단해 신호가 보수적으로 바뀝니다"
    if parameter in {"std_mult", "bb_std_mult"}:
        if lowered:
            return "볼린저밴드 폭이 좁아져 신호가 자주 생기고, 더 민감하게 반응합니다"
        if raised:
            return "볼린저밴드 폭이 넓어져 신호가 줄고, 더 신중하게 판단합니다"
    if parameter in {"period", "rsi_period", "bb_period", "volume_period"}:
        if lowered:
            return "최근 데이터 비중이 커져, 더 빠르게 반응하는 설정입니다"
        if raised:
            return "더 긴 데이터를 평균내어, 신호가 부드럽고 느리게 바뀝니다"
    if parameter == "k":
        if lowered:
            return "약한 돌파도 매수 후보가 되어, 더 공격적으로 진입합니다"
        if raised:
            return "강한 돌파만 매수하게 되어, 더 보수적으로 진입합니다"

    return "최근 성과 기준으로 신호의 민감도와 보수성을 다시 맞춘 조정입니다"


def build_indicator_explainer_lines(strategy_name: str, min_confidence: float) -> list[str]:
    """초보자를 위한 지표 설명을 전략별로 덧붙인다."""
    common_lines = [
        "",
        "지표 설명:",
        f"  confidence: 봇이 신호를 얼마나 강하게 보는지 나타내는 내부 점수이며, {min_confidence:.0%} 미만이면 실제 매수를 막습니다",
    ]

    if strategy_name == "score":
        return common_lines + [
            "  RSI: 최근 상승/하락 힘을 0~100으로 본 지표입니다. 낮을수록 과매도, 높을수록 과매수로 봅니다",
            "  RSI 반등/하락: RSI가 직전 캔들보다 올라가면 반등 시작, 내려가면 약세 강화로 해석합니다",
            "  MACD: 단기와 장기 평균의 차이입니다. MACD가 시그널선 위면 상승 쪽, 아래면 하락 쪽 힘이 더 강하다고 봅니다",
            "  히스토그램: MACD와 시그널선 차이입니다. 증가하면 상승 탄력이 붙고, 감소하면 힘이 약해진다고 봅니다",
            "  BB / %B: 볼린저밴드 안에서 가격 위치를 보는 값입니다. 하단에 가까우면 눌림, 상단에 가까우면 과열로 봅니다",
            "  거래량 평균 이상: 거래량이 평소보다 많아야 신호 신뢰도가 높다고 판단합니다",
            "  추세장/횡보장/변동장: 시장 상태에 따라 필요한 점수 기준을 다르게 적용합니다",
        ]

    if strategy_name == "rsi":
        return common_lines + [
            "  RSI: 최근 상승/하락 힘을 0~100으로 나타냅니다. 보통 낮으면 싸게 눌린 구간, 높으면 과열 구간으로 봅니다",
        ]

    if strategy_name == "macd":
        return common_lines + [
            "  MACD: 단기 평균이 장기 평균보다 얼마나 강한지 보여주는 지표입니다",
            "  Signal: MACD의 평균선입니다. MACD가 이 선을 위로 돌파하면 골든크로스, 아래로 내려가면 데드크로스로 봅니다",
        ]

    if strategy_name == "bollinger":
        return common_lines + [
            "  볼린저밴드: 최근 평균 가격 주변에 상단/하단 밴드를 그린 지표입니다",
            "  하단 터치: 평균보다 많이 내려온 상태라 반등 후보로 보고, 상단 터치는 과열 구간으로 봅니다",
        ]

    if strategy_name == "volatility_breakout":
        return common_lines + [
            "  변동성 돌파: 전일 고가-저가 폭을 이용해 오늘 강한 돌파가 나오는지 보는 방식입니다",
            "  k 값: 돌파 기준을 얼마나 보수적/공격적으로 잡을지 정하는 계수입니다",
        ]

    if strategy_name == "ensemble":
        return common_lines + [
            "  앙상블: 여러 전략의 의견을 동시에 보고, 같은 방향 표가 많이 모일 때만 신호를 냅니다",
            "  과반수 또는 2/3 이상 동의가 필요하므로 단일 전략보다 보수적으로 움직입니다",
        ]

    return common_lines
