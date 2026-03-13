"""cryptolight 진입점 - 전략 실행, 시그널 알림, paper/live trading, 리스크 관리"""

import argparse
import signal
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler

from cryptolight.bot.command_handler import CommandHandler
from cryptolight.bot.telegram_bot import TelegramBot
from cryptolight.config import get_settings
from cryptolight.exchange.candle_cache import CandleCache
from cryptolight.health import HealthMonitor
from cryptolight.market.regime import MarketRegime
from cryptolight.strategy.volume_filter import VolumeFilter
from cryptolight.exchange.upbit import UpbitClient
from cryptolight.execution.base import BaseBroker
from cryptolight.execution.live_broker import LiveBroker
from cryptolight.execution.paper_broker import PaperBroker
from cryptolight.risk.cooldown import TradeCooldown
from cryptolight.risk.position_sizer import PositionSizer
from cryptolight.risk.risk_guard import RiskGuard
from cryptolight.storage.repository import TradeRepository
from cryptolight.storage.strategy_tracker import StrategyTracker
import html as html_mod

from cryptolight.bot.ai_assistant import AIAssistant, markdown_to_telegram_html
from cryptolight.evaluation import (
    PerformanceEvaluator,
    StrategyArena,
    AdaptiveController,
    ParameterOptimizer,
)
from cryptolight.evaluation.optimizer import PARAM_RANGES
from cryptolight.market.screener import run_screening_pipeline
from cryptolight.strategy import create_strategy
from cryptolight.strategy.score_based import REGIME_WEIGHTS
from cryptolight.utils import setup_logger

# 중복 시그널 방지: symbol -> action (스레드 안전)
_last_signals: dict[str, str] = {}
_signal_lock = threading.Lock()
# 모듈 레벨 캐시/쿨다운 (main()에서 초기화)
_candle_cache: CandleCache | None = None
_cooldown: TradeCooldown | None = None
_position_sizer: PositionSizer | None = None
_health: HealthMonitor | None = None
_regime_detector: MarketRegime | None = None
_volume_filter: VolumeFilter | None = None
_market_snapshots: dict[str, dict] = {}
_ai_assistant: AIAssistant | None = None
_cmd_handler: CommandHandler | None = None
_scheduler: BlockingScheduler | None = None
_active_strategy_name: str = ""  # HIGH-1: mutable 전략명 (자기개선 루프에서 전환)
_active_strategy_params: dict = {}  # 자동 조정된 활성 전략 파라미터


def _explain_indicators(indicators: dict) -> str:
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

    bb_pct = indicators.get("bb_position")
    if bb_pct is not None:
        if bb_pct <= 0.2:
            desc = "밴드 하단 — 저점 근처"
        elif bb_pct >= 0.8:
            desc = "밴드 상단 — 고점 근처"
        else:
            desc = "밴드 중간 — 보통 구간"
        lines.append(f"  볼린저: {desc}")

    return "\n".join(lines)


def _get_effective_strategy_name(settings) -> str:
    return _active_strategy_name or settings.strategy_name


def _get_effective_strategy_params(settings, strategy_name: str | None = None) -> dict:
    name = strategy_name or _get_effective_strategy_name(settings)
    if name == _get_effective_strategy_name(settings):
        return dict(_active_strategy_params)
    return {}


def _build_strategy_instance(settings, strategy_name: str | None = None, params: dict | None = None):
    name = strategy_name or _get_effective_strategy_name(settings)
    strategy_params = dict(params) if params is not None else _get_effective_strategy_params(settings, name)
    if name == "ensemble":
        return create_strategy("ensemble", strategy_names=settings.ensemble_strategy_list)
    return create_strategy(name, **strategy_params)


def _collect_tunable_params(strategy_name: str, strategy) -> dict:
    if strategy_name == "rsi":
        return {
            "period": strategy.period,
            "oversold": strategy.oversold,
            "overbought": strategy.overbought,
        }
    if strategy_name == "macd":
        return {
            "fast": strategy.fast,
            "slow": strategy.slow,
            "signal_period": strategy.signal_period,
        }
    if strategy_name == "bollinger":
        return {
            "period": strategy.period,
            "std_mult": strategy.std_mult,
        }
    if strategy_name == "volatility_breakout":
        return {"k": strategy.k}
    if strategy_name == "score":
        return {
            "rsi_period": strategy.rsi_period,
            "rsi_oversold": strategy.rsi_oversold,
            "rsi_overbought": strategy.rsi_overbought,
            "macd_fast": strategy.macd_fast,
            "macd_slow": strategy.macd_slow,
            "macd_signal": strategy.macd_signal,
            "bb_period": strategy.bb_period,
            "bb_std_mult": strategy.bb_std_mult,
            "volume_period": strategy.volume_period,
        }
    return {}


def _format_param_value(value) -> str:
    if value is None:
        return "기본값"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}"
    return str(value)


def _format_datetime_for_user(dt, timezone_name: str) -> str:
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


def _format_remaining_time(seconds: float) -> str:
    if seconds <= 0:
        return "없음"
    total_minutes = int(seconds // 60)
    hours, minutes = divmod(total_minutes, 60)
    if hours > 0:
        return f"{hours}시간 {minutes}분"
    return f"{minutes}분"


def _parameter_label(strategy_name: str, parameter: str) -> str:
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


def _parameter_change_explainer(strategy_name: str, parameter: str, old_value, new_value) -> str:
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


def _load_active_strategy_parameters(repo: TradeRepository, settings, logger=None) -> dict:
    strategy_name = _get_effective_strategy_name(settings)
    params = repo.get_strategy_parameters(strategy_name)
    global _active_strategy_params
    _active_strategy_params = params
    if logger and params:
        logger.info("적용된 자동 조정 파라미터: %s", params)
    return params


def run_strategy(
    client: UpbitClient,
    bot: TelegramBot | None,
    broker: BaseBroker | None,
    risk_guard: RiskGuard | None,
    symbols: list[str],
    settings,
):
    """각 종목에 대해 전략을 실행하고 시그널을 전송한다."""
    logger = setup_logger("cryptolight.main")
    strategy_name = _get_effective_strategy_name(settings)
    strategy = _build_strategy_instance(settings, strategy_name)

    for symbol in symbols:
        # 캔들 캐시 활용
        candle_count = strategy.required_candle_count() * 2
        interval = settings.candle_interval
        cache_key = _candle_cache.make_key(symbol, interval, candle_count) if _candle_cache else ""
        candles = (_candle_cache.get(cache_key) if _candle_cache else None)
        if candles is None:
            candles = client.get_candles(symbol, interval=interval, count=candle_count)
            if _candle_cache:
                _candle_cache.put(cache_key, candles)
        ticker = client.get_ticker(symbol)

        logger.info(
            "%s 현재가: %s KRW (변동: %+.2f%%)",
            symbol, f"{ticker.price:,.0f}", ticker.change_rate * 100,
        )

        # 급등/급락 알림 (음소거 시 건너뜀)
        if bot and abs(ticker.change_rate) >= settings.surge_alert_threshold:
            if not (_cmd_handler and _cmd_handler.muted):
                bot.send_surge_alert(symbol, ticker.price, ticker.change_rate)

        # 손절/익절 체크 (Paper + Live 모두 지원)
        if risk_guard:
            _sl_avg_price = 0.0
            _sl_quantity = 0.0
            pos = broker.get_position(symbol)
            if pos:
                _sl_avg_price = pos.avg_price
                _sl_quantity = pos.quantity

            if _sl_quantity > 0 and _sl_avg_price > 0:
                sl_tp = risk_guard.check_stop_loss_take_profit(
                    symbol, _sl_avg_price, _sl_quantity, ticker.price,
                )
                if sl_tp == "stop_loss":
                    order = broker.sell_market(symbol, _sl_quantity, ticker.price, reason="손절 트리거")
                    if order:
                        logger.warning("손절 매도 실행: %s %.8f @ %s", symbol, _sl_quantity, f"{ticker.price:,.0f}")
                        if bot:
                            bot.send_message(f"\U0001f534 <b>손절 매도</b>\n{symbol} @ {ticker.price:,.0f} KRW")
                    continue
                elif sl_tp == "take_profit":
                    order = broker.sell_market(symbol, _sl_quantity, ticker.price, reason="익절 트리거")
                    if order:
                        logger.info("익절 매도 실행: %s %.8f @ %s", symbol, _sl_quantity, f"{ticker.price:,.0f}")
                        if bot:
                            bot.send_message(f"\U0001f7e2 <b>익절 매도</b>\n{symbol} @ {ticker.price:,.0f} KRW")
                    continue
                elif sl_tp == "trailing_stop":
                    order = broker.sell_market(symbol, _sl_quantity, ticker.price, reason="트레일링 스톱")
                    if order:
                        logger.warning("트레일링 스톱 매도: %s %.8f @ %s", symbol, _sl_quantity, f"{ticker.price:,.0f}")
                        if bot:
                            bot.send_message(f"\U0001f7e1 <b>트레일링 스톱</b>\n{symbol} @ {ticker.price:,.0f} KRW")
                    continue

        # 시장 국면 감지
        regime_info = None
        if _regime_detector and len(candles) >= _regime_detector.required_candle_count():
            regime_info = _regime_detector.detect(candles)
            logger.info("시장 국면: %s (ADX=%.1f, 매매가중치=%.1f)", regime_info["regime"], regime_info["adx"], regime_info["trade_weight"])

        # score 전략에 국면 연동
        if hasattr(strategy, "regime") and regime_info:
            strategy.regime = regime_info["regime"]

        # 전략 분석
        signal_result = strategy.analyze(candles)
        signal_result.symbol = symbol

        # 거래량 필터 적용
        if _volume_filter:
            signal_result = _volume_filter.apply(signal_result, candles)

        logger.info(
            "[%s] %s — %s (신뢰도: %.0f%%, RSI: %s)",
            signal_result.action.upper(), symbol, signal_result.reason,
            signal_result.confidence * 100, signal_result.indicators.get("rsi", "N/A"),
        )

        # 중복 시그널 방지 (스레드 안전) — 실행 전에는 읽기만, 업데이트는 주문 성공 후
        with _signal_lock:
            prev = _last_signals.get(symbol)
            if prev == signal_result.action and signal_result.action != "hold":
                logger.info("중복 시그널 스킵: %s → %s", symbol, signal_result.action)
                continue
            # hold 시그널이면 이전 기록을 지워 다음 buy/sell 허용
            if signal_result.action == "hold":
                _last_signals.pop(symbol, None)

        # 매수 실행
        if broker and signal_result.action == "buy":
            # confidence 게이트
            if signal_result.confidence < settings.min_confidence:
                logger.info(
                    "신뢰도 부족 차단: %s confidence=%.2f < threshold=%.2f",
                    symbol, signal_result.confidence, settings.min_confidence,
                )
                continue
            # 쿨다운 체크
            if _cooldown:
                can, reason = _cooldown.can_trade(symbol)
                if not can:
                    logger.info("쿨다운 차단: %s — %s", symbol, reason)
                    continue

            # 리스크 체크
            if risk_guard:
                _balance_krw = broker.get_balance_krw()
                _positions = broker.get_positions()
                _active_positions = sum(1 for p in _positions.values() if p.quantity > 0)
                _already_holding = broker.is_holding(symbol)

                check = risk_guard.check_buy(
                    symbol, settings.max_order_amount_krw,
                    balance_krw=_balance_krw,
                    active_positions=_active_positions,
                    already_holding=_already_holding,
                )
                if not check.allowed:
                    logger.warning("매수 차단: %s — %s", symbol, check.reason)
                    if bot:
                        bot.send_message(f"\u26a0\ufe0f <b>매수 차단</b>\n{symbol}: {check.reason}")
                    continue

            # 포지션 사이징 (시장 국면 가중치 반영)
            if _position_sizer:
                equity = broker.get_equity({symbol: ticker.price})
                confidence = signal_result.confidence
                if regime_info:
                    confidence *= regime_info["trade_weight"]
                order_amount = _position_sizer.calculate(equity, confidence)
            else:
                order_amount = settings.max_order_amount_krw

            order = broker.buy_market(symbol, order_amount, ticker.price, reason=signal_result.reason, strategy=strategy_name)
            if order:
                with _signal_lock:
                    _last_signals[symbol] = "buy"
                if _cooldown:
                    _cooldown.record_trade(symbol)
                logger.info("매수 체결: %s %s KRW [%s]", symbol, f"{order_amount:,.0f}", settings.trade_mode)
                if bot:
                    coin_name = symbol.split("-")[1]
                    qty_str = f"{order.quantity:.8f}".rstrip("0").rstrip(".")
                    explain = _explain_indicators(signal_result.indicators)
                    bot.send_message(
                        f"\U0001f7e2 <b>매수 체결</b>\n"
                        f"종목: {symbol} ({coin_name})\n"
                        f"매수금액: {order_amount:,.0f} KRW\n"
                        f"체결가격: {ticker.price:,.0f} KRW\n"
                        f"매수수량: {qty_str}개\n"
                        f"사유: {signal_result.reason}\n"
                        f"\n<b>지표 해설</b>\n<pre>{html_mod.escape(explain)}</pre>"
                    )

        elif broker and signal_result.action == "sell":
            _sell_qty = 0.0
            _sell_order = None
            pos = broker.get_position(symbol)
            if pos:
                _sell_qty = pos.quantity
                _sell_order = broker.sell_market(symbol, pos.quantity, ticker.price, reason=signal_result.reason, strategy=strategy_name)
                if _sell_order:
                    logger.info("매도 체결: %s %.8f [%s]", symbol, pos.quantity, settings.trade_mode)
            else:
                logger.info("매도 시그널이지만 보유 수량 없음: %s", symbol)

            if _sell_order:
                with _signal_lock:
                    _last_signals[symbol] = "sell"
            if _sell_order and bot:
                coin_name = symbol.split("-")[1]
                qty_str = f"{_sell_qty:.8f}".rstrip("0").rstrip(".")
                proceeds = _sell_qty * ticker.price
                explain = _explain_indicators(signal_result.indicators)
                bot.send_message(
                    f"\U0001f534 <b>매도 체결</b>\n"
                    f"종목: {symbol} ({coin_name})\n"
                    f"매도금액: {proceeds:,.0f} KRW\n"
                    f"체결가격: {ticker.price:,.0f} KRW\n"
                    f"매도수량: {qty_str}개\n"
                    f"사유: {signal_result.reason}\n"
                    f"\n<b>지표 해설</b>\n<pre>{html_mod.escape(explain)}</pre>"
                )

        # 시장 상태 수집 (텔레그램 요약용)
        _market_snapshots[symbol] = {
            "price": ticker.price,
            "change": ticker.change_rate * 100,
            "rsi": signal_result.indicators.get("rsi"),
            "action": signal_result.action,
            "regime": regime_info["regime"] if regime_info else "N/A",
            "adx": regime_info["adx"] if regime_info else 0,
            "weight": regime_info["trade_weight"] if regime_info else 1.0,
        }

        # 텔레그램 전송 (hold 제외, 음소거 시 건너뜀)
        if bot and signal_result.action != "hold":
            if not (_cmd_handler and _cmd_handler.muted):
                bot.send_signal(signal_result, price=ticker.price)
            else:
                logger.info("알림 음소거 중 — 시그널 전송 생략")
        elif bot and signal_result.action == "hold":
            logger.info("관망 시그널 — 텔레그램 전송 생략")

    # HIGH-3: Live 모드 잔고 캐시 클리어 (다음 주기에 갱신)
    _market_snapshots.pop("_live_balances", None)

    # 포트폴리오 요약 + 시장 상태 (MEDIUM-3: 이미 수집된 가격 재활용)
    if broker is not None:
        prices = {sym: snap["price"] for sym, snap in _market_snapshots.items() if isinstance(snap, dict) and "price" in snap}
        # 보유 중이지만 현재 symbols에 없는 종목도 가격 조회
        for pos_symbol, pos in broker.get_positions().items():
            if pos.quantity > 0 and pos_symbol not in prices:
                try:
                    pos_ticker = client.get_ticker(pos_symbol)
                    prices[pos_symbol] = pos_ticker.price
                except Exception:
                    logger.warning("보유 종목 가격 조회 실패: %s", pos_symbol)
        summary = broker.summary_text(prices)

        # 시장 상태 라인 추가
        market_lines = []
        for sym, snap in _market_snapshots.items():
            rsi_val = f"{snap['rsi']:.1f}" if snap['rsi'] else "N/A"
            market_lines.append(
                f"{sym}: RSI={rsi_val} | {snap['regime']}(ADX={snap['adx']:.0f}) | {snap['change']:+.1f}%"
            )
        market_text = "\n".join(market_lines)

        logger.info("=== Paper Trading 현황 ===\n%s", summary)
        if bot:
            # 이번 주기 거래 내역 구성
            cycle_trades_lines = []
            for sym, snap in _market_snapshots.items():
                if snap["action"] == "buy":
                    pos = broker.get_position(sym)
                    if pos and pos.quantity > 0:
                        cycle_trades_lines.append(
                            f"  \U0001f7e2 <b>{sym.split('-')[1]}</b> 매수 — "
                            f"{snap['price']:,.0f}원에 구매"
                        )
                elif snap["action"] == "sell":
                    cycle_trades_lines.append(
                        f"  \U0001f534 <b>{sym.split('-')[1]}</b> 매도 — "
                        f"{snap['price']:,.0f}원에 판매"
                    )

            msg_parts = ["\U0001f4b0 <b>Paper Trading 현황</b>"]
            if cycle_trades_lines:
                msg_parts.append("\n\U0001f4dd <b>이번 주기 거래</b>")
                msg_parts.extend(cycle_trades_lines)
            msg_parts.append(f"\n<pre>{html_mod.escape(summary)}</pre>")
            msg_parts.append(f"\n\U0001f4ca <b>시장 상태</b>\n<pre>{html_mod.escape(market_text)}</pre>")
            bot.send_message("\n".join(msg_parts))


def strategy_job(
    client: UpbitClient,
    bot: TelegramBot | None,
    broker: BaseBroker | None,
    risk_guard: RiskGuard | None,
    symbols: list[str],
    settings,
):
    """스케줄러에서 호출되는 전략 래퍼. 에러 시 해당 주기만 스킵."""
    logger = setup_logger("cryptolight.main")
    try:
        run_strategy(client, bot, broker, risk_guard, symbols, settings)
        if _health:
            _health.record_success()
    except Exception:
        logger.exception("전략 실행 중 에러 발생 — 이번 주기 스킵")
        if _health:
            _health.record_failure()


def daily_summary_job(
    bot: TelegramBot,
    broker: BaseBroker | None,
    repo: TradeRepository,
    client: UpbitClient,
    symbols: list[str],
):
    """매일 09:00 KST에 실행되는 일일 요약 job"""
    logger = setup_logger("cryptolight.main")
    try:
        pnl_data = repo.get_daily_pnl()
        positions_summary = ""
        if broker is not None:
            prices = {}
            for symbol in symbols:
                ticker = client.get_ticker(symbol)
                prices[symbol] = ticker.price
            # 보유 중이지만 symbols에 없는 종목도 가격 조회
            for pos_symbol, pos in broker.get_positions().items():
                if pos.quantity > 0 and pos_symbol not in prices:
                    try:
                        pos_ticker = client.get_ticker(pos_symbol)
                        prices[pos_symbol] = pos_ticker.price
                    except Exception:
                        pass
            positions_summary = broker.summary_text(prices)
        # 오늘 거래 내역 조회
        today_trades = repo.get_trades(limit=50)
        from datetime import datetime
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_trades = [t for t in today_trades if t.timestamp.startswith(today_str)]
        # 전략별 성과 추가
        tracker = StrategyTracker(repo)
        strategy_summary = tracker.summary_text()
        # 보유 코인 상세 정보 구성
        holdings = []
        if broker is not None:
            for pos_sym, pos in broker.get_positions().items():
                if pos.quantity > 0:
                    cur_price = prices.get(pos_sym, 0)
                    holdings.append({
                        "symbol": pos_sym,
                        "coin": pos_sym.split("-")[1] if "-" in pos_sym else pos_sym,
                        "quantity": pos.quantity,
                        "avg_price": pos.avg_price,
                        "current_price": cur_price,
                        "eval_amount": pos.quantity * cur_price,
                        "cost": pos.quantity * pos.avg_price,
                        "pnl": (cur_price - pos.avg_price) * pos.quantity,
                    })
        bot.send_daily_summary(pnl_data, positions_summary, today_trades, holdings, broker.get_balance_krw() if broker else 0)
        if strategy_summary and "데이터 없음" not in strategy_summary:
            bot.send_message(f"<b>전략별 성과</b>\n<pre>{strategy_summary}</pre>")
        logger.info("일일 요약 전송 완료")
    except Exception:
        logger.exception("일일 요약 전송 실패")


def self_improvement_job(
    client: UpbitClient,
    repo: TradeRepository,
    bot: TelegramBot | None,
    settings,
):
    """주간 자기개선 루프: 성과 평가 → Arena 경쟁 → 전략 전환 판단."""
    logger = setup_logger("cryptolight.main")
    if not settings.enable_auto_optimization:
        return

    try:
        current_strategy = _get_effective_strategy_name(settings)
        # 1. 성과 평가
        evaluator = PerformanceEvaluator(repo)
        perf_summary = evaluator.summary_text(days=settings.arena_lookback_days)
        logger.info("자기개선 루프 시작\n%s", perf_summary)

        # 2. Arena 경쟁 — 캔들 데이터 수집
        symbol = settings.symbol_list[0] if settings.symbol_list else "KRW-BTC"
        candles = client.get_candles(symbol, interval="day", count=settings.arena_lookback_days)

        arena = StrategyArena(
            initial_balance=settings.paper_initial_balance,
            order_amount=settings.max_order_amount_krw,
            n_folds=3,
            slippage_pct=settings.backtest_slippage_pct,
            spread_pct=settings.backtest_spread_pct,
        )
        arena_results = arena.compete(candles)
        arena_text = arena.summary_text(arena_results)
        logger.info(arena_text)

        # 3. 전략 전환 판단
        controller = AdaptiveController(
            repo=repo,
            min_sharpe_improvement=settings.min_sharpe_improvement,
            cooldown_days=settings.switch_cooldown_days,
        )

        switch_decision = controller.should_switch(
            current_strategy, arena_results, evaluator,
        )
        logger.info("전환 판단: %s", switch_decision["reason"])

        if switch_decision["switch"]:
            controller.record_switch(
                switch_decision["from"], switch_decision["to"], switch_decision["reason"],
            )
            # HIGH-1: mutable 전략명 실제 적용
            global _active_strategy_name
            _active_strategy_name = switch_decision["to"]
            _load_active_strategy_parameters(repo, settings, logger)
            msg = (
                f"전략 전환: {switch_decision['from']} → {switch_decision['to']}\n"
                f"사유: {switch_decision['reason']}"
            )
            logger.warning(msg)
            if bot:
                bot.send_message(f"<b>전략 자동 전환</b>\n<pre>{html_mod.escape(msg)}</pre>")

        # 4. 롤백 체크
        active_strategy = _get_effective_strategy_name(settings)
        rollback = controller.check_rollback(active_strategy, evaluator)
        if rollback:
            logger.warning("롤백 제안: %s", rollback["reason"])
            if bot:
                bot.send_message(
                    f"<b>롤백 제안</b>\n"
                    f"{html_mod.escape(rollback['from'])} → {html_mod.escape(rollback['to'])}\n"
                    f"사유: {html_mod.escape(rollback['reason'])}"
                )

        # 5. 텔레그램 요약 전송
        if bot:
            bot.send_message(
                f"<b>자기개선 루프 완료</b>\n<pre>{html_mod.escape(arena_text)}</pre>\n"
                f"전환 판단: {html_mod.escape(switch_decision['reason'])}"
            )

    except Exception:
        logger.exception("자기개선 루프 실행 중 에러")


def _build_market_context() -> str:
    """AI 질문에 첨부할 현재 시장 컨텍스트를 구성한다."""
    if not _market_snapshots:
        return ""
    lines = []
    for sym, snap in _market_snapshots.items():
        rsi_val = f"{snap['rsi']:.1f}" if snap.get('rsi') else "N/A"
        lines.append(
            f"{sym}: 가격={snap.get('price', 0):,.0f}원, "
            f"변동={snap.get('change', 0):+.1f}%, "
            f"RSI={rsi_val}, "
            f"국면={snap.get('regime', 'N/A')}(ADX={snap.get('adx', 0):.0f}), "
            f"판단={snap.get('action', 'hold')}"
        )
    return "\n".join(lines)


def _send_market_info(bot: TelegramBot, settings) -> None:
    """현재 시장 상태를 텔레그램으로 전송한다."""
    if not _market_snapshots:
        bot.send_message("아직 시장 데이터가 없습니다. 다음 주기까지 대기해주세요.")
        return

    lines = []
    for sym, snap in _market_snapshots.items():
        rsi_val = snap.get("rsi")
        rsi_str = f"{rsi_val:.1f}" if rsi_val else "N/A"
        regime = snap.get("regime", "N/A")
        price = snap.get("price", 0)
        change = snap.get("change", 0)
        action = snap.get("action", "hold")

        action_kr = {"buy": "매수", "sell": "매도", "hold": "관망"}.get(action, action)

        # RSI 해설
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

        # 국면 해설
        regime_desc = {
            "trending": "추세장 — 한 방향으로 강하게 움직이는 중",
            "sideways": "횡보장 — 큰 움직임 없이 제자리",
            "volatile": "변동장 — 위아래로 크게 흔들리는 중",
        }.get(regime, "")

        # 판단 해설
        action_desc = {
            "buy": "매수 조건 충족 — 봇이 매수를 시도합니다",
            "sell": "매도 조건 충족 — 봇이 매도를 시도합니다",
            "hold": "매매 조건 미충족 — 지켜보는 중",
        }.get(action, "")

        # 변동률 해설
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

    strategy_name = _get_effective_strategy_name(settings)
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
    lines.extend(_build_strategy_criteria_lines(settings))
    lines.append(f"분석 주기: {settings.schedule_interval_minutes}분마다 자동 분석")

    bot.send_message(
        f"\U0001f4ca <b>시장 상태</b>\n<pre>{html_mod.escape(chr(10).join(lines))}</pre>"
    )


def _build_strategy_criteria_lines(settings) -> list[str]:
    """현재 전략의 매수/매도 기준을 사람이 읽기 쉽게 요약한다."""
    strategy_name = _get_effective_strategy_name(settings)
    strategy = _build_strategy_instance(settings, strategy_name)
    active_params = _collect_tunable_params(strategy_name, strategy)
    tuned = bool(_get_effective_strategy_params(settings, strategy_name))
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
        for snap in _market_snapshots.values():
            regime = snap.get("regime")
            if regime in REGIME_WEIGHTS and regime not in seen_regimes:
                seen_regimes.append(regime)
        regimes = seen_regimes or ["trending", "sideways", "volatile"]
        for regime in regimes:
            weights = REGIME_WEIGHTS[regime]
            regime_kr = {
                "trending": "추세장",
                "sideways": "횡보장",
                "volatile": "변동장",
            }.get(regime, regime)
            lines.append(
                f"  {regime_kr}: 매수 {weights['buy_threshold']}점 이상 / 매도 {weights['sell_threshold']}점 이상"
            )
        lines.append(f"  추가 게이트: confidence {settings.min_confidence:.0%} 이상일 때만 실제 매수")
        lines.extend(_build_indicator_explainer_lines(strategy_name, min_confidence=settings.min_confidence))
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
    lines.extend(_build_indicator_explainer_lines(strategy_name, min_confidence=settings.min_confidence))
    return lines


def _build_indicator_explainer_lines(strategy_name: str, min_confidence: float) -> list[str]:
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


def _send_strategy_criteria(bot: TelegramBot, settings) -> None:
    lines = _build_strategy_criteria_lines(settings)
    bot.send_message(
        f"\U0001f4d8 <b>매수/매도 기준</b>\n<pre>{html_mod.escape(chr(10).join(lines))}</pre>"
    )


def _build_tuning_history_lines(repo: TradeRepository, settings) -> list[str]:
    strategy_name = _get_effective_strategy_name(settings)
    strategy = _build_strategy_instance(settings, strategy_name)
    current_params = _collect_tunable_params(strategy_name, strategy)
    recent = repo.get_recent_parameter_adjustments(limit=5, strategy=strategy_name)
    latest = repo.get_latest_parameter_adjustment(strategy_name)
    next_run = "알 수 없음"
    if _scheduler:
        job = _scheduler.get_job("parameter_tuning")
        if job and getattr(job, "next_run_time", None):
            next_run = _format_datetime_for_user(job.next_run_time, settings.app_timezone)

    remaining_cooldown = "없음"
    if latest and settings.parameter_tuning_cooldown_hours > 0:
        applied_at = datetime.fromisoformat(latest["applied_at"])
        remaining_seconds = (
            settings.parameter_tuning_cooldown_hours * 3600
            - (datetime.now() - applied_at).total_seconds()
        )
        remaining_cooldown = _format_remaining_time(remaining_seconds)

    lines = [
        f"현재 전략: {strategy_name}",
        "현재 파라미터:",
    ]
    for parameter, value in current_params.items():
        lines.append(f"  {_parameter_label(strategy_name, parameter)}: {_format_param_value(value)}")
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
            f"{_parameter_label(row['strategy'], row['parameter'])}: "
            f"{_format_param_value(row['old_value'])} -> {_format_param_value(row['new_value'])}"
        )
        if row.get("explanation"):
            lines.append(f"    설명: {row['explanation']}")
        if row.get("metric_summary"):
            lines.append(f"    근거: {row['metric_summary']}")
    return lines


def _send_tuning_history(bot: TelegramBot, repo: TradeRepository, settings) -> None:
    lines = _build_tuning_history_lines(repo, settings)
    bot.send_message(
        f"\U0001f6e0\ufe0f <b>자동 조정 이력</b>\n<pre>{html_mod.escape(chr(10).join(lines))}</pre>"
    )


def _send_parameter_tuning_update(
    bot: TelegramBot,
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
            f"  {_parameter_label(strategy_name, item['parameter'])}: "
            f"{_format_param_value(item['old_value'])} -> {_format_param_value(item['new_value'])}"
        )
        if item.get("explanation"):
            lines.append(f"    초보자 설명: {item['explanation']}")

    bot.send_message(
        f"\U0001f6e0\ufe0f <b>기준 자동 조정 적용</b>\n<pre>{html_mod.escape(chr(10).join(lines))}</pre>"
    )


def _run_parameter_tuning(
    repo: TradeRepository,
    settings,
    strategy_name: str,
    candles,
    bot: TelegramBot | None = None,
) -> dict:
    logger = setup_logger("cryptolight.main")
    if not settings.enable_auto_parameter_tuning:
        return {"applied": False, "summary": "파라미터 자동 조정 비활성"}

    if strategy_name not in PARAM_RANGES:
        return {
            "applied": False,
            "summary": f"{strategy_name} 전략은 자동 파라미터 조정 대상이 아닙니다",
        }

    latest = repo.get_latest_parameter_adjustment(strategy_name)
    if latest and settings.parameter_tuning_cooldown_hours > 0:
        applied_at = datetime.fromisoformat(latest["applied_at"])
        hours_since = (datetime.now() - applied_at).total_seconds() / 3600
        if hours_since < settings.parameter_tuning_cooldown_hours:
            return {
                "applied": False,
                "summary": (
                    f"{strategy_name} 파라미터 조정 쿨다운 중 "
                    f"({hours_since:.1f}/{settings.parameter_tuning_cooldown_hours}시간)"
                ),
            }

    optimizer = ParameterOptimizer(
        initial_balance=settings.paper_initial_balance,
        order_amount=settings.max_order_amount_krw,
        n_folds=settings.parameter_tuning_n_folds,
        min_wf_consistency=settings.parameter_tuning_min_wf_consistency,
        slippage_pct=settings.backtest_slippage_pct,
        spread_pct=settings.backtest_spread_pct,
    )

    current_strategy = _build_strategy_instance(settings, strategy_name)
    current_params = _collect_tunable_params(strategy_name, current_strategy)
    baseline = optimizer.evaluate_params(strategy_name, current_params, candles)
    result = optimizer.optimize(
        strategy_name,
        candles,
        n_trials=settings.optimizer_trials,
    )

    if result.valid_trials == 0 or not result.best_params:
        return {
            "applied": False,
            "summary": f"{strategy_name} 파라미터 조정 후보 없음",
        }

    baseline_sharpe = baseline.get("sharpe", 0.0) if baseline else 0.0
    improvement = result.best_sharpe - baseline_sharpe
    metric_summary = (
        f"Sharpe {baseline_sharpe:.3f} -> {result.best_sharpe:.3f}, "
        f"WF 일관성 {result.best_wf_consistency:.0f}%, "
        f"수익 {result.best_return_pct:+.2f}%"
    )

    if improvement < settings.parameter_min_sharpe_improvement:
        return {
            "applied": False,
            "summary": (
                f"{strategy_name} 파라미터 유지 "
                f"(개선폭 {improvement:.3f} < 기준 {settings.parameter_min_sharpe_improvement:.3f})"
            ),
            "metric_summary": metric_summary,
        }

    explanations = {
        key: _parameter_change_explainer(strategy_name, key, current_params.get(key), value)
        for key, value in result.best_params.items()
        if current_params.get(key) != value
    }
    changed = repo.apply_parameter_adjustments(
        strategy=strategy_name,
        new_params=result.best_params,
        reason=(
            f"최근 {settings.arena_lookback_days}개 캔들 기준 "
            "Walk-Forward 통과 후보 중 Sharpe 개선"
        ),
        metric_summary=metric_summary,
        explanations=explanations,
        previous_params=current_params,
    )

    if not changed:
        return {
            "applied": False,
            "summary": f"{strategy_name} 파라미터 유지 (현재 값과 최적값 동일)",
            "metric_summary": metric_summary,
        }

    global _active_strategy_params
    if strategy_name == _get_effective_strategy_name(settings):
        _active_strategy_params = repo.get_strategy_parameters(strategy_name)

    logger.info("파라미터 자동 조정 적용: %s %s", strategy_name, changed)
    if bot:
        _send_parameter_tuning_update(bot, strategy_name, changed, metric_summary)

    return {
        "applied": True,
        "summary": f"{strategy_name} 파라미터 자동 조정 적용",
        "metric_summary": metric_summary,
        "changed": changed,
    }


def parameter_tuning_job(
    client: UpbitClient,
    repo: TradeRepository,
    bot: TelegramBot | None,
    symbols: list[str],
    settings,
):
    """더 짧은 주기로 현재 전략 파라미터만 미세 조정한다."""
    logger = setup_logger("cryptolight.main")
    if not settings.enable_auto_parameter_tuning:
        return

    try:
        strategy_name = _get_effective_strategy_name(settings)
        strategy = _build_strategy_instance(settings, strategy_name)
        symbol = symbols[0] if symbols else (settings.symbol_list[0] if settings.symbol_list else "KRW-BTC")
        candle_count = max(
            settings.parameter_tuning_lookback_candles,
            strategy.required_candle_count() * 3,
        )
        candles = client.get_candles(
            symbol,
            interval=settings.candle_interval,
            count=candle_count,
        )
        result = _run_parameter_tuning(
            repo=repo,
            settings=settings,
            strategy_name=strategy_name,
            candles=candles,
            bot=bot,
        )
        logger.info("파라미터 조정 job 완료: %s", result["summary"])
    except Exception:
        logger.exception("파라미터 조정 job 실패")


def command_loop(
    cmd_handler: CommandHandler,
    scheduler: BlockingScheduler,
    bot: TelegramBot | None,
    broker: BaseBroker | None = None,
    repo: TradeRepository | None = None,
    client: UpbitClient | None = None,
    symbols: list[str] | None = None,
    settings=None,
    stop_event: threading.Event | None = None,
):
    """명령어 long polling 루프 (전용 스레드에서 실행). 킬스위치 감지 시 스케줄러 종료."""
    logger = setup_logger("cryptolight.main")
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
                status_text = _health.summary_text() if _health else "헬스 모니터 미초기화"
                bot.send_message(f"\U0001f4cb <b>봇 상태</b>\n<pre>{status_text}</pre>")
                cmd_handler.reset_status()
            if cmd_handler.info_requested and bot and settings:
                _send_market_info(bot, settings)
                cmd_handler.reset_info()
            if cmd_handler.criteria_requested and bot and settings:
                _send_strategy_criteria(bot, settings)
                cmd_handler.reset_criteria()
            if cmd_handler.tuning_requested and bot and repo and settings:
                _send_tuning_history(bot, repo, settings)
                cmd_handler.reset_tuning()
            # /ask 질문 처리
            if _ai_assistant and bot:
                for question in cmd_handler.get_pending_questions():
                    context = _build_market_context()
                    answer = _ai_assistant.ask(question, context=context)
                    remaining = _ai_assistant.remaining_today
                    bot.send_message(
                        f"\U0001f916 <b>AI 답변</b>\n\n"
                        f"{markdown_to_telegram_html(answer)}\n\n"
                        f"<i>남은 횟수: {remaining}회/일</i>"
                    )
        except Exception:
            logger.exception("명령어 폴링 중 에러 발생")


def main():
    parser = argparse.ArgumentParser(description="cryptolight trading bot")
    parser.add_argument("--once", action="store_true", help="1회 실행 후 종료")
    args = parser.parse_args()

    settings = get_settings()
    logger = setup_logger("cryptolight.main", settings.log_level, settings.log_file)

    once_mode = args.once or settings.schedule_interval_minutes == 0

    logger.info("cryptolight v0.1.0 시작")
    logger.info("거래 모드: %s", settings.trade_mode)
    logger.info("대상 종목: %s", settings.symbol_list)

    # 텔레그램 봇 초기화
    bot = None
    cmd_handler = None
    if settings.telegram_bot_token and settings.telegram_chat_id:
        bot = TelegramBot(settings.telegram_bot_token, settings.telegram_chat_id)
        global _cmd_handler
        cmd_handler = CommandHandler(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            poll_timeout_seconds=settings.telegram_poll_timeout_seconds,
            request_timeout_seconds=settings.telegram_request_timeout_seconds,
        )
        _cmd_handler = cmd_handler
        bot.send_startup(settings.symbol_list, settings.trade_mode)
        logger.info("텔레그램 봇 연결됨")
    else:
        logger.warning("텔레그램 설정 없음 — 알림 비활성화")

    # 명령어 확인 (킬스위치)
    if cmd_handler:
        cmd_handler.poll_commands()
        if cmd_handler.kill_switch:
            logger.warning("킬스위치 활성 — 실행 중단")
            if bot:
                bot.close()
            cmd_handler.close()
            return

    # 브로커 초기화
    broker = None
    repo = TradeRepository(db_path=Path(settings.db_path))
    _load_active_strategy_parameters(repo, settings, logger)
    risk_guard = RiskGuard(
        max_order_amount_krw=settings.max_order_amount_krw,
        daily_loss_limit_krw=settings.daily_loss_limit_krw,
        max_positions=settings.max_positions,
        stop_loss_pct=settings.stop_loss_pct,
        take_profit_pct=settings.take_profit_pct,
        trailing_stop_pct=settings.trailing_stop_pct,
        repo=repo,
        commission_rate=settings.commission_rate,
    )

    client = UpbitClient(settings.upbit_access_key, settings.upbit_secret_key)

    # 캔들 캐시, 쿨다운, 포지션 사이징, 헬스체크, 국면감지, 거래량필터 초기화
    global _candle_cache, _cooldown, _position_sizer, _health, _regime_detector, _volume_filter, _ai_assistant
    _health = HealthMonitor()
    _regime_detector = MarketRegime()
    _volume_filter = VolumeFilter()
    if settings.google_api_key:
        _ai_assistant = AIAssistant(
            api_key=settings.google_api_key,
            model=settings.gemini_model,
            daily_limit=settings.ask_daily_limit,
        )
        logger.info("AI 어시스턴트 활성화 (모델: %s, 일일 %d회 제한)", settings.gemini_model, settings.ask_daily_limit)
    _candle_cache = CandleCache(ttl_seconds=settings.candle_cache_ttl)
    _cooldown = TradeCooldown(
        cooldown_seconds=settings.trade_cooldown_seconds,
        max_orders_per_hour=settings.max_orders_per_hour,
    )
    _position_sizer = PositionSizer(
        method=settings.position_sizing_method,
        fixed_amount=settings.max_order_amount_krw,
        risk_pct=settings.position_risk_pct,
        max_amount=settings.absolute_max_order_krw,
    )
    logger.info(
        "포지션 사이징: %s, 쿨다운: %ds, 캔들캐시 TTL: %ds",
        settings.position_sizing_method, settings.trade_cooldown_seconds, settings.candle_cache_ttl,
    )

    if settings.trade_mode == "paper":
        broker = PaperBroker(initial_balance=settings.paper_initial_balance, repo=repo, commission_rate=settings.commission_rate)
        logger.info("Paper trading 초기화: 초기 자금 %s KRW", f"{broker.initial_balance:,.0f}")
    elif settings.trade_mode == "live":
        broker = LiveBroker(
            client=client, repo=repo,
            absolute_max_order_krw=settings.absolute_max_order_krw,
            commission_rate=settings.commission_rate,
        )
        logger.info("Live trading 초기화 (하드캡: %s KRW)", f"{settings.absolute_max_order_krw:,.0f}")
        if bot:
            bot.send_message("\u26a0\ufe0f <b>LIVE 모드</b>로 실행 중입니다.")

    logger.info(
        "리스크 설정: 최대주문 %s, 일일손실한도 %s, 손절 %s%%, 익절 %s%%",
        f"{settings.max_order_amount_krw:,.0f}",
        f"{settings.daily_loss_limit_krw:,.0f}",
        settings.stop_loss_pct,
        settings.take_profit_pct,
    )

    # ── 자동 종목 스크리닝 ──
    symbols = settings.symbol_list
    if settings.auto_select_symbols:
        logger.info("자동 종목 스크리닝 시작 (상위 %d개, 최소 거래대금 %s원)",
                     settings.top_volume_limit, f"{settings.min_daily_volume_krw:,}")
        try:
            screening = run_screening_pipeline(
                client=client,
                strategy_name=settings.strategy_name,
                top_limit=settings.top_volume_limit,
                min_volume_krw=settings.min_daily_volume_krw,
                min_sharpe=settings.min_backtest_sharpe,
                max_correlation=settings.max_correlation,
                max_positions=settings.max_positions,
                candle_interval=settings.candle_interval,
            )
            if screening.selected:
                symbols = screening.selected
                logger.info("자동 스크리닝 결과: %s", symbols)
                if bot:
                    details_lines = []
                    for sym in screening.selected:
                        d = screening.backtest_details.get(sym, {})
                        if d and not d.get("skipped"):
                            details_lines.append(
                                f"  {sym}: Sharpe={d['sharpe']:.4f}, "
                                f"수익={d['return_pct']:+.2f}%, "
                                f"거래={d['total_trades']}회"
                            )
                        else:
                            details_lines.append(f"  {sym}: 백테스트 데이터 없음")
                    msg = (
                        f"후보: {len(screening.candidates)}개\n"
                        f"백테스트 통과: {len(screening.backtest_passed)}개\n"
                        f"상관관계 제외: {screening.correlation_removed}\n"
                        f"최종 선정:\n" + "\n".join(details_lines)
                    )
                    bot.send_message(
                        f"\U0001f50d <b>자동 종목 스크리닝</b>\n<pre>{html_mod.escape(msg)}</pre>"
                    )
            else:
                logger.warning("자동 스크리닝 결과 없음 — 기본 종목 사용: %s", settings.symbol_list)
        except Exception:
            logger.exception("자동 스크리닝 실패 — 기본 종목 사용")

    # ── 1회 실행 모드 ──
    if once_mode:
        logger.info("1회 실행 모드")
        try:
            run_strategy(client, bot, broker, risk_guard, symbols, settings)
        finally:
            if _ai_assistant:
                _ai_assistant.close()
            if bot:
                bot.close()
            if cmd_handler:
                cmd_handler.close()
            client.close()
            repo.close()
        logger.info("cryptolight 종료")
        return

    # ── 스케줄러 모드 ──
    logger.info("스케줄러 모드: %d분 간격", settings.schedule_interval_minutes)
    scheduler = BlockingScheduler(timezone=settings.app_timezone)
    global _scheduler
    _scheduler = scheduler

    scheduler.add_job(
        strategy_job,
        "interval",
        minutes=settings.schedule_interval_minutes,
        max_instances=1,
        misfire_grace_time=60,
        args=[client, bot, broker, risk_guard, symbols, settings],
        id="strategy",
        next_run_time=None,  # 첫 실행은 아래에서 즉시 수행
    )

    # 명령어 폴링: 전용 스레드에서 long polling (즉시 응답)
    cmd_stop_event = threading.Event()
    if cmd_handler:
        cmd_thread = threading.Thread(
            target=command_loop,
            args=[cmd_handler, scheduler, bot, broker, repo, client, symbols, settings, cmd_stop_event],
            daemon=True,
            name="command-poll",
        )
        cmd_thread.start()

    if bot:
        scheduler.add_job(
            daily_summary_job,
            "cron",
            hour=settings.daily_summary_hour,
            minute=settings.daily_summary_minute,
            args=[bot, broker, repo, client, symbols],
            id="daily_summary",
        )

    # 자기개선 루프: 매주 일요일 03:00 KST
    if settings.enable_auto_optimization:
        scheduler.add_job(
            self_improvement_job,
            "cron",
            day_of_week=settings.self_improvement_day_of_week,
            hour=settings.self_improvement_hour,
            minute=settings.self_improvement_minute,
            args=[client, repo, bot, settings],
            id="self_improvement",
        )
        logger.info(
            "전략 전환 루프 활성화: %s %02d:%02d 실행 (%s)",
            settings.self_improvement_day_of_week,
            settings.self_improvement_hour,
            settings.self_improvement_minute,
            settings.app_timezone,
        )

    if settings.enable_auto_parameter_tuning and settings.parameter_tuning_interval_hours > 0:
        scheduler.add_job(
            parameter_tuning_job,
            "interval",
            hours=settings.parameter_tuning_interval_hours,
            max_instances=1,
            misfire_grace_time=300,
            args=[client, repo, bot, symbols, settings],
            id="parameter_tuning",
        )
        logger.info(
            "파라미터 조정 루프 활성화: %d시간마다 실행, 쿨다운 %d시간",
            settings.parameter_tuning_interval_hours,
            settings.parameter_tuning_cooldown_hours,
        )

    # ── 웹 대시보드 ──
    if settings.enable_web:
        try:
            import uvicorn
            from cryptolight.web.app import app as web_app, configure as web_configure

            web_configure(
                market_snapshots=_market_snapshots,
                broker=broker,
                repo=repo,
                health=_health,
                settings=settings,
            )
            web_thread = threading.Thread(
                target=uvicorn.run,
                kwargs={"app": web_app, "host": settings.web_host, "port": settings.web_port, "log_level": "warning"},
                daemon=True,
                name="web-dashboard",
            )
            web_thread.start()
            logger.info("웹 대시보드 시작: http://%s:%d", settings.web_host, settings.web_port)
        except ImportError:
            logger.warning("웹 대시보드 비활성: fastapi/uvicorn 미설치 (pip install cryptolight[web])")

    # Graceful shutdown
    def _shutdown(signum, _frame):
        sig_name = signal.Signals(signum).name
        logger.info("시그널 수신: %s — graceful shutdown", sig_name)
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # 스케줄러 시작 전 1회 즉시 실행
    strategy_job(client, bot, broker, risk_guard, symbols, settings)

    try:
        # next_run_time을 설정하여 다음 interval부터 실행되도록
        scheduler.reschedule_job("strategy", trigger="interval", minutes=settings.schedule_interval_minutes)
        scheduler.start()
    finally:
        logger.info("스케줄러 종료 — 리소스 정리")
        _scheduler = None
        if _ai_assistant:
            _ai_assistant.close()
        if bot:
            bot.send_message("\U0001f6d1 cryptolight 종료됩니다.")
            bot.close()
        if cmd_handler:
            cmd_handler.close()
        client.close()
        repo.close()

    logger.info("cryptolight 종료")


if __name__ == "__main__":
    main()
