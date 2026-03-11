"""cryptolight 진입점 - 전략 실행, 시그널 알림, paper/live trading, 리스크 관리"""

import argparse
import signal
import threading
from pathlib import Path

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
from cryptolight.evaluation import PerformanceEvaluator, StrategyArena, AdaptiveController
from cryptolight.market.screener import run_screening_pipeline
from cryptolight.strategy import create_strategy
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
_active_strategy_name: str = ""  # HIGH-1: mutable 전략명 (자기개선 루프에서 전환)


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
    # HIGH-1: mutable 전략명 사용 (자기개선 루프에서 전환 가능)
    strategy_name = _active_strategy_name or settings.strategy_name
    if strategy_name == "ensemble":
        strategy = create_strategy("ensemble", strategy_names=settings.ensemble_strategy_list)
    else:
        strategy = create_strategy(strategy_name)

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
            if isinstance(broker, PaperBroker):
                pos = broker.positions.get(symbol)
                if pos and pos.quantity > 0:
                    _sl_avg_price = pos.avg_price
                    _sl_quantity = pos.quantity
            elif isinstance(broker, LiveBroker):
                currency = symbol.split("-")[1]
                coin_bal = client.get_balance(currency)
                if coin_bal and coin_bal.available > 0:
                    _sl_quantity = coin_bal.available
                    _sl_avg_price = coin_bal.avg_buy_price if hasattr(coin_bal, "avg_buy_price") and coin_bal.avg_buy_price else 0.0

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

        # 중복 시그널 방지 (스레드 안전)
        with _signal_lock:
            prev = _last_signals.get(symbol)
            if prev == signal_result.action:
                logger.info("중복 시그널 스킵: %s → %s", symbol, signal_result.action)
                continue
            _last_signals[symbol] = signal_result.action

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
                if isinstance(broker, PaperBroker):
                    _balance_krw = broker.balance_krw
                    _active_positions = sum(
                        1 for p in broker.positions.values() if p.quantity > 0
                    )
                    _already_holding = (
                        symbol in broker.positions
                        and broker.positions[symbol].quantity > 0
                    )
                elif isinstance(broker, LiveBroker):
                    # HIGH-3: 잔고 일괄 조회 재활용
                    if "_live_balances" not in _market_snapshots:
                        all_balances = client.get_balances()
                        _market_snapshots["_live_balances"] = {b.currency: b for b in all_balances}
                    bal_map = _market_snapshots["_live_balances"]
                    krw_bal = bal_map.get("KRW")
                    _balance_krw = krw_bal.available if krw_bal else 0.0
                    _active_positions = sum(
                        1 for b in bal_map.values()
                        if b.currency != "KRW" and b.available > 0
                    )
                    currency = symbol.split("-")[1]
                    coin_bal = bal_map.get(currency)
                    _already_holding = bool(coin_bal and coin_bal.available > 0)
                else:
                    _balance_krw = 0.0
                    _active_positions = 0
                    _already_holding = False

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
                equity = broker.get_equity({symbol: ticker.price}) if isinstance(broker, PaperBroker) else settings.max_order_amount_krw
                confidence = signal_result.confidence
                if regime_info:
                    confidence *= regime_info["trade_weight"]
                order_amount = _position_sizer.calculate(equity, confidence)
            else:
                order_amount = settings.max_order_amount_krw

            order = broker.buy_market(symbol, order_amount, ticker.price, reason=signal_result.reason, strategy=strategy_name)
            if order:
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
            if isinstance(broker, PaperBroker):
                pos = broker.positions.get(symbol)
                if pos and pos.quantity > 0:
                    _sell_qty = pos.quantity
                    _sell_order = broker.sell_market(symbol, pos.quantity, ticker.price, reason=signal_result.reason, strategy=strategy_name)
                    if _sell_order:
                        logger.info("매도 체결: %s %.8f [%s]", symbol, pos.quantity, settings.trade_mode)
                else:
                    logger.info("매도 시그널이지만 보유 수량 없음: %s", symbol)
            elif isinstance(broker, LiveBroker):
                currency = symbol.split("-")[1]
                balance = client.get_balance(currency)
                if balance and balance.available > 0:
                    _sell_qty = balance.available
                    _sell_order = broker.sell_market(symbol, balance.available, ticker.price, reason=signal_result.reason, strategy=strategy_name)
                    if _sell_order:
                        logger.info("매도 체결: %s %.8f [live]", symbol, balance.available)
                else:
                    logger.info("매도 시그널이지만 보유 수량 없음: %s", symbol)

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

    # Paper trading 요약 + 시장 상태 (MEDIUM-3: 이미 수집된 가격 재활용)
    if isinstance(broker, PaperBroker):
        prices = {sym: snap["price"] for sym, snap in _market_snapshots.items() if isinstance(snap, dict) and "price" in snap}
        # 보유 중이지만 현재 symbols에 없는 종목도 가격 조회
        for pos_symbol, pos in broker.positions.items():
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
            bot.send_message(
                f"\U0001f4b0 <b>Paper Trading 현황</b>\n<pre>{html_mod.escape(summary)}</pre>"
                f"\n\U0001f4ca <b>시장 상태</b>\n<pre>{html_mod.escape(market_text)}</pre>"
            )


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
        if isinstance(broker, PaperBroker):
            prices = {}
            for symbol in symbols:
                ticker = client.get_ticker(symbol)
                prices[symbol] = ticker.price
            positions_summary = broker.summary_text(prices)
        # 전략별 성과 추가
        tracker = StrategyTracker(repo)
        strategy_summary = tracker.summary_text()
        bot.send_daily_summary(pnl_data, positions_summary)
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
            settings.strategy_name, arena_results, evaluator,
        )
        logger.info("전환 판단: %s", switch_decision["reason"])

        if switch_decision["switch"]:
            controller.record_switch(
                switch_decision["from"], switch_decision["to"], switch_decision["reason"],
            )
            # HIGH-1: mutable 전략명 실제 적용
            global _active_strategy_name
            _active_strategy_name = switch_decision["to"]
            msg = (
                f"전략 전환: {switch_decision['from']} → {switch_decision['to']}\n"
                f"사유: {switch_decision['reason']}"
            )
            logger.warning(msg)
            if bot:
                bot.send_message(f"<b>전략 자동 전환</b>\n<pre>{html_mod.escape(msg)}</pre>")

        # 4. 롤백 체크
        rollback = controller.check_rollback(settings.strategy_name, evaluator)
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

    strategy_desc = {
        "rsi": "RSI (과매수/과매도 기반)",
        "macd": "MACD (추세 전환 감지)",
        "bollinger": "볼린저밴드 (가격 이탈 감지)",
        "ensemble": "앙상블 (여러 전략 종합)",
    }.get(settings.strategy_name, settings.strategy_name)

    lines.append(f"\n전략: {strategy_desc}")
    lines.append(f"분석 주기: {settings.schedule_interval_minutes}분마다 자동 분석")

    bot.send_message(
        f"\U0001f4ca <b>시장 상태</b>\n<pre>{html_mod.escape(chr(10).join(lines))}</pre>"
    )


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
    while not (stop_event and stop_event.is_set()):
        try:
            cmd_handler.poll_commands()
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
        cmd_handler = CommandHandler(settings.telegram_bot_token, settings.telegram_chat_id)
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
    risk_guard = RiskGuard(
        max_order_amount_krw=settings.max_order_amount_krw,
        daily_loss_limit_krw=settings.daily_loss_limit_krw,
        max_positions=settings.max_positions,
        stop_loss_pct=settings.stop_loss_pct,
        take_profit_pct=settings.take_profit_pct,
        trailing_stop_pct=settings.trailing_stop_pct,
        repo=repo,
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
        broker = PaperBroker(initial_balance=settings.paper_initial_balance, repo=repo)
        logger.info("Paper trading 초기화: 초기 자금 %s KRW", f"{broker.initial_balance:,.0f}")
    elif settings.trade_mode == "live":
        broker = LiveBroker(
            client=client, repo=repo,
            absolute_max_order_krw=settings.absolute_max_order_krw,
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
    scheduler = BlockingScheduler(timezone="Asia/Seoul")

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
            hour=9,
            minute=0,
            args=[bot, broker, repo, client, symbols],
            id="daily_summary",
        )

    # 자기개선 루프: 매주 일요일 03:00 KST
    if settings.enable_auto_optimization:
        scheduler.add_job(
            self_improvement_job,
            "cron",
            day_of_week="sun",
            hour=3,
            minute=0,
            args=[client, repo, bot, settings],
            id="self_improvement",
        )
        logger.info("자기개선 루프 활성화: 매주 일요일 03:00 실행")

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
