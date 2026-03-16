"""Telegram/reporting helpers extracted from the main runtime entrypoint."""

from __future__ import annotations

from datetime import datetime
import html as html_mod
from typing import Any, Callable

from cryptolight.bot.formatters import (
    build_indicator_explainer_lines,
    format_datetime_for_user,
    format_param_value,
    format_remaining_time,
    parameter_label,
)


def build_market_context(
    *,
    get_market_snapshots_copy: Callable[[], dict[str, dict]],
) -> str:
    snapshots = get_market_snapshots_copy()
    if not snapshots:
        return ""

    lines = []
    for sym, snap in snapshots.items():
        rsi_val = f"{snap['rsi']:.1f}" if snap.get("rsi") else "N/A"
        lines.append(
            f"{sym}: 가격={snap.get('price', 0):,.0f}원, "
            f"변동={snap.get('change', 0):+.1f}%, "
            f"RSI={rsi_val}, "
            f"국면={snap.get('regime', 'N/A')}(ADX={snap.get('adx', 0):.0f}), "
            f"판단={snap.get('action', 'hold')}"
        )
    return "\n".join(lines)


def build_strategy_criteria_lines(
    settings,
    *,
    build_strategy_instance: Callable[..., Any],
    get_effective_strategy_name: Callable[[Any], str],
    get_effective_strategy_params: Callable[..., dict],
    get_market_snapshots_copy: Callable[[], dict[str, dict]],
    regime_weights: dict[str, dict[str, float]],
) -> list[str]:
    strategy_name = get_effective_strategy_name(settings)
    strategy = build_strategy_instance(settings, strategy_name)
    active_params = strategy.get_tunable_params()
    tuned = bool(get_effective_strategy_params(settings, strategy_name))
    lines = ["현재 매수/매도 기준:"]

    if strategy_name == "score":
        lines.extend([
            (
                "  매수 팩터: "
                f"RSI<={strategy.rsi_oversold:.0f}, RSI 반등, "
                f"MACD 상향({strategy.macd_fast}/{strategy.macd_slow}/{strategy.macd_signal}), "
                f"히스토그램 증가, BB 하단/%B<0.2(기간 {strategy.bb_period}, 표준편차 {strategy.bb_std_mult:.2f}), "
                f"거래량 평균 이상(기간 {strategy.volume_period})"
            ),
            (
                "  매도 팩터: "
                f"RSI>={strategy.rsi_overbought:.0f}, RSI 하락, "
                f"MACD 하향({strategy.macd_fast}/{strategy.macd_slow}/{strategy.macd_signal}), "
                f"히스토그램 감소, BB 상단/%B>0.8(기간 {strategy.bb_period}, 표준편차 {strategy.bb_std_mult:.2f}), "
                f"거래량 평균 이상(기간 {strategy.volume_period})"
            ),
        ])
        lines.append(
            "  현재 적용값: "
            f"RSI 기간 {strategy.rsi_period}, "
            f"과매도 {strategy.rsi_oversold:.0f}, 과매수 {strategy.rsi_overbought:.0f}, "
            f"MACD {strategy.macd_fast}/{strategy.macd_slow}/{strategy.macd_signal}, "
            f"BB 기간 {strategy.bb_period}, 표준편차 {strategy.bb_std_mult:.2f}, "
            f"거래량 기간 {strategy.volume_period} "
            f"({'자동 조정값' if tuned else '기본값'})"
        )
        seen_regimes: list[str] = []
        for snap in get_market_snapshots_copy().values():
            regime = snap.get("regime")
            if regime in regime_weights and regime not in seen_regimes:
                seen_regimes.append(regime)
        regimes = seen_regimes or ["trending", "sideways", "volatile"]
        for regime in regimes:
            weights = regime_weights[regime]
            regime_kr = {
                "trending": "추세장",
                "sideways": "횡보장",
                "volatile": "변동장",
            }.get(regime, regime)
            lines.append(
                f"  {regime_kr}: 매수 {weights['buy_threshold']}점 이상 / 매도 {weights['sell_threshold']}점 이상"
            )
        lines.append(f"  추가 게이트: confidence {settings.min_confidence:.0%} 이상일 때만 실제 매수")
        lines.extend(build_indicator_explainer_lines(strategy_name, min_confidence=settings.min_confidence))
        return lines

    if strategy_name == "rsi":
        lines.append(f"  매수: RSI <= {strategy.oversold:.0f} (기간 {strategy.period})")
        lines.append(f"  매도: RSI >= {strategy.overbought:.0f} (기간 {strategy.period})")
        lines.append(
            f"  현재 적용값: RSI 기간 {active_params['period']}, 과매도 {active_params['oversold']:.0f}, "
            f"과매수 {active_params['overbought']:.0f} "
            f"({'자동 조정값' if tuned else '기본값'})"
        )
    elif strategy_name == "macd":
        lines.append(
            f"  매수: 직전엔 MACD < Signal, 현재 MACD > Signal (골든크로스, {strategy.fast}/{strategy.slow}/{strategy.signal_period})"
        )
        lines.append(
            f"  매도: 직전엔 MACD > Signal, 현재 MACD < Signal (데드크로스, {strategy.fast}/{strategy.slow}/{strategy.signal_period})"
        )
        lines.append(
            f"  현재 적용값: MACD 빠른선 {active_params['fast']}, 느린선 {active_params['slow']}, "
            f"시그널 {active_params['signal_period']} "
            f"({'자동 조정값' if tuned else '기본값'})"
        )
    elif strategy_name == "bollinger":
        lines.append(f"  매수: 종가가 볼린저 하단 이하 (period={strategy.period}, std={strategy.std_mult})")
        lines.append(f"  매도: 종가가 볼린저 상단 이상 (period={strategy.period}, std={strategy.std_mult})")
        lines.append(
            f"  현재 적용값: 볼린저 기간 {active_params['period']}, 표준편차 {active_params['std_mult']:.2f} "
            f"({'자동 조정값' if tuned else '기본값'})"
        )
    elif strategy_name == "volatility_breakout":
        lines.append(f"  매수: 현재가 >= 시가 + 전일변동폭*k (k={strategy.k})")
        lines.append("  매도: 현재가가 당일 시가 아래로 내려오면 하락 반전으로 판단")
        lines.append(
            f"  현재 적용값: k={active_params['k']:.2f} "
            f"({'자동 조정값' if tuned else '기본값'})"
        )
    elif strategy_name == "ensemble":
        strategy_names = ", ".join(settings.ensemble_strategy_list)
        lines.append(f"  구성 전략: {strategy_names}")
        lines.append("  매수/매도: 참여 전략의 2/3 이상 또는 과반수가 같은 방향일 때")
    else:
        lines.append(f"  전략별 상세 기준 요약 미지원: {strategy_name}")

    lines.append(f"  추가 게이트: confidence {settings.min_confidence:.0%} 이상일 때만 실제 매수")
    lines.extend(build_indicator_explainer_lines(strategy_name, min_confidence=settings.min_confidence))
    return lines


def send_market_info(
    bot,
    settings,
    *,
    get_market_snapshots_copy: Callable[[], dict[str, dict]],
    get_effective_strategy_name: Callable[[Any], str],
    build_strategy_criteria_lines: Callable[[Any], list[str]],
) -> None:
    snapshots = get_market_snapshots_copy()
    if not snapshots:
        bot.send_message("아직 시장 데이터가 없습니다. 다음 주기까지 대기해주세요.")
        return

    lines = []
    for sym, snap in snapshots.items():
        rsi_val = snap.get("rsi")
        rsi_str = f"{rsi_val:.1f}" if rsi_val else "N/A"
        regime = snap.get("regime", "N/A")
        price = snap.get("price", 0)
        change = snap.get("change", 0)
        action = snap.get("action", "hold")

        action_kr = {"buy": "매수", "sell": "매도", "hold": "관망"}.get(action, action)

        if rsi_val is not None:
            if rsi_val <= 30:
                rsi_desc = "과매도 (싸게 살 기회)"
            elif rsi_val >= 70:
                rsi_desc = "과매수 (비싸서 위험)"
            elif rsi_val <= 40:
                rsi_desc = "약간 저평가"
            elif rsi_val >= 60:
                rsi_desc = "약간 고평가"
            else:
                rsi_desc = "중립 (뚜렷한 방향 없음)"
        else:
            rsi_desc = ""

        regime_desc = {
            "trending": "추세장 — 한 방향으로 강하게 움직이는 중",
            "sideways": "횡보장 — 큰 움직임 없이 제자리",
            "volatile": "변동장 — 위아래로 크게 흔들리는 중",
        }.get(regime, "")

        action_desc = {
            "buy": "매수 조건 충족 — 봇이 매수를 시도합니다",
            "sell": "매도 조건 충족 — 봇이 매도를 시도합니다",
            "hold": "매매 조건 미충족 — 지켜보는 중",
        }.get(action, "")

        if abs(change) >= 5:
            change_desc = " (큰 변동!)" if change > 0 else " (큰 하락!)"
        elif abs(change) >= 2:
            change_desc = " (상승세)" if change > 0 else " (하락세)"
        else:
            change_desc = " (안정적)"

        lines.append(f"── {sym} ──")
        lines.append(f"  현재가: {price:,.0f} KRW ({change:+.1f}%){change_desc}")
        lines.append(f"  RSI: {rsi_str} — {rsi_desc}")
        lines.append(f"  국면: {regime} — {regime_desc}")
        lines.append(f"  봇 판단: {action_kr} — {action_desc}")

    strategy_name = get_effective_strategy_name(settings)
    strategy_desc = {
        "rsi": "RSI (과매수/과매도 기반)",
        "macd": "MACD (추세 전환 감지)",
        "bollinger": "볼린저밴드 (가격 이탈 감지)",
        "score": "스코어 (여러 지표 합산)",
        "ensemble": "앙상블 (여러 전략 종합)",
        "volatility_breakout": "변동성 돌파",
    }.get(strategy_name, strategy_name)

    lines.append(f"\n전략: {strategy_desc}")
    lines.append("")
    lines.extend(build_strategy_criteria_lines(settings))
    lines.append(f"분석 주기: {settings.schedule_interval_minutes}분마다 자동 분석")

    bot.send_message(
        f"\U0001f4ca <b>시장 상태</b>\n<pre>{html_mod.escape(chr(10).join(lines))}</pre>"
    )


def send_strategy_criteria(
    bot,
    settings,
    *,
    build_strategy_criteria_lines: Callable[[Any], list[str]],
) -> None:
    lines = build_strategy_criteria_lines(settings)
    bot.send_message(
        f"\U0001f4d8 <b>매수/매도 기준</b>\n<pre>{html_mod.escape(chr(10).join(lines))}</pre>"
    )


def build_tuning_history_lines(
    repo,
    settings,
    *,
    get_effective_strategy_name: Callable[[Any], str],
    build_strategy_instance: Callable[..., Any],
    scheduler,
) -> list[str]:
    strategy_name = get_effective_strategy_name(settings)
    strategy = build_strategy_instance(settings, strategy_name)
    current_params = strategy.get_tunable_params()
    recent = repo.get_recent_parameter_adjustments(limit=5, strategy=strategy_name)
    latest = repo.get_latest_parameter_adjustment(strategy_name)
    next_run = "알 수 없음"
    if scheduler:
        job = scheduler.get_job("parameter_tuning")
        if job and getattr(job, "next_run_time", None):
            next_run = format_datetime_for_user(job.next_run_time, settings.app_timezone)

    remaining_cooldown = "없음"
    if latest and settings.parameter_tuning_cooldown_hours > 0:
        applied_at = datetime.fromisoformat(latest["applied_at"])
        remaining_seconds = (
            settings.parameter_tuning_cooldown_hours * 3600
            - (datetime.now() - applied_at).total_seconds()
        )
        remaining_cooldown = format_remaining_time(remaining_seconds)

    lines = [
        f"현재 전략: {strategy_name}",
        "현재 파라미터:",
    ]
    for parameter, value in current_params.items():
        lines.append(f"  {parameter_label(strategy_name, parameter)}: {format_param_value(value)}")
    lines.extend([
        "",
        "조정 스케줄:",
        f"  다음 자동조정: {next_run}",
        f"  실행 주기: {settings.parameter_tuning_interval_hours}시간마다",
        f"  조정 쿨다운: {settings.parameter_tuning_cooldown_hours}시간",
        f"  남은 쿨다운: {remaining_cooldown}",
        "",
        "최근 자동 조정:",
    ])
    if not recent:
        lines.append("  아직 자동 조정 이력이 없습니다")
        return lines

    seen_keys: set[tuple[str, str]] = set()
    for row in recent:
        key = (row["strategy"], row["parameter"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        lines.append(
            f"  {row['applied_at'][:16]} "
            f"{parameter_label(row['strategy'], row['parameter'])}: "
            f"{format_param_value(row['old_value'])} -> {format_param_value(row['new_value'])}"
        )
        if row.get("explanation"):
            lines.append(f"    설명: {row['explanation']}")
        if row.get("metric_summary"):
            lines.append(f"    근거: {row['metric_summary']}")
    return lines


def send_tuning_history(
    bot,
    repo,
    settings,
    *,
    build_tuning_history_lines: Callable[[Any, Any], list[str]],
) -> None:
    lines = build_tuning_history_lines(repo, settings)
    bot.send_message(
        f"\U0001f6e0\ufe0f <b>자동 조정 이력</b>\n<pre>{html_mod.escape(chr(10).join(lines))}</pre>"
    )


def send_parameter_tuning_update(
    bot,
    strategy_name: str,
    changed: list[dict],
    metric_summary: str,
) -> None:
    lines = [
        f"전략: {strategy_name}",
        f"평가 결과: {metric_summary}",
        "",
        "변경 내용:",
    ]
    for item in changed:
        lines.append(
            f"  {parameter_label(strategy_name, item['parameter'])}: "
            f"{format_param_value(item['old_value'])} -> {format_param_value(item['new_value'])}"
        )
        if item.get("explanation"):
            lines.append(f"    초보자 설명: {item['explanation']}")

    bot.send_message(
        f"\U0001f527 <b>파라미터 자동 조정</b>\n<pre>{html_mod.escape(chr(10).join(lines))}</pre>"
    )
