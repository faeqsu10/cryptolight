"""Strategy execution helpers extracted from the main runtime entrypoint."""

from __future__ import annotations

import html as html_mod
import logging
import threading
from typing import Any, Callable


def run_strategy(
    client,
    bot,
    broker,
    risk_guard,
    symbols: list[str],
    settings,
    *,
    logger: logging.Logger,
    get_effective_strategy_name: Callable[[Any], str],
    build_strategy_instance: Callable[..., Any],
    candle_cache,
    update_market_snapshot: Callable[..., None],
    cmd_handler,
    regime_detector,
    volume_filter,
    signal_lock: threading.Lock,
    last_signals: dict[str, str],
    cooldown,
    position_sizer,
    market_snapshots: dict[str, dict],
    explain_indicators: Callable[[dict], str],
) -> None:
    """Run strategy analysis for all symbols and emit side effects."""
    strategy_name = get_effective_strategy_name(settings)
    strategy = build_strategy_instance(settings, strategy_name)

    for symbol in symbols:
        candle_count = strategy.required_candle_count() * 2
        interval = settings.candle_interval
        cache_key = candle_cache.make_key(symbol, interval, candle_count) if candle_cache else ""
        candles = candle_cache.get(cache_key) if candle_cache else None
        if candles is None:
            candles = client.get_candles(symbol, interval=interval, count=candle_count)
            if candle_cache:
                candle_cache.put(cache_key, candles)
        ticker = client.get_ticker(symbol)

        logger.info(
            "%s 현재가: %s KRW (변동: %+.2f%%)",
            symbol, f"{ticker.price:,.0f}", ticker.change_rate * 100,
        )
        update_market_snapshot(symbol, price=ticker.price, change=ticker.change_rate * 100)

        if bot and abs(ticker.change_rate) >= settings.surge_alert_threshold and bot.should_notify("signal"):
            if not (cmd_handler and cmd_handler.muted):
                bot.send_surge_alert(symbol, ticker.price, ticker.change_rate)

        if risk_guard:
            avg_price = 0.0
            quantity = 0.0
            pos = broker.get_position(symbol)
            if pos:
                avg_price = pos.avg_price
                quantity = pos.quantity

            if quantity > 0 and avg_price > 0:
                sl_tp = risk_guard.check_stop_loss_take_profit(symbol, avg_price, quantity, ticker.price)
                if sl_tp == "stop_loss":
                    order = broker.sell_market(symbol, quantity, ticker.price, reason="손절 트리거")
                    if order:
                        pnl_pct = (ticker.price - avg_price) / avg_price * 100 if avg_price else 0
                        pnl_krw = (ticker.price - avg_price) * quantity
                        proceeds = ticker.price * quantity
                        qty_str = f"{quantity:.8f}".rstrip("0").rstrip(".")
                        logger.warning("손절 매도 실행: %s %.8f @ %s", symbol, quantity, f"{ticker.price:,.0f}")
                        update_market_snapshot(
                            symbol,
                            price=ticker.price,
                            change=ticker.change_rate * 100,
                            action="sell",
                            trade_qty=quantity,
                            trade_amount=proceeds,
                            trade_reason="손절 트리거",
                        )
                        if bot:
                            bot.send_message(
                                f"\U0001f534 <b>손절 매도</b>\n"
                                f"종목: {symbol}\n"
                                f"매도금액: {proceeds:,.0f} KRW\n"
                                f"체결가격: {ticker.price:,.0f} KRW\n"
                                f"매수평단: {avg_price:,.0f} KRW\n"
                                f"수량: {qty_str}개\n"
                                f"손익: {pnl_krw:+,.0f} KRW ({pnl_pct:+.1f}%)"
                            )
                    continue
                if sl_tp == "take_profit":
                    order = broker.sell_market(symbol, quantity, ticker.price, reason="익절 트리거")
                    if order:
                        pnl_pct = (ticker.price - avg_price) / avg_price * 100 if avg_price else 0
                        pnl_krw = (ticker.price - avg_price) * quantity
                        proceeds = ticker.price * quantity
                        qty_str = f"{quantity:.8f}".rstrip("0").rstrip(".")
                        logger.info("익절 매도 실행: %s %.8f @ %s", symbol, quantity, f"{ticker.price:,.0f}")
                        update_market_snapshot(
                            symbol,
                            price=ticker.price,
                            change=ticker.change_rate * 100,
                            action="sell",
                            trade_qty=quantity,
                            trade_amount=proceeds,
                            trade_reason="익절 트리거",
                        )
                        if bot:
                            bot.send_message(
                                f"\U0001f7e2 <b>익절 매도</b>\n"
                                f"종목: {symbol}\n"
                                f"매도금액: {proceeds:,.0f} KRW\n"
                                f"체결가격: {ticker.price:,.0f} KRW\n"
                                f"매수평단: {avg_price:,.0f} KRW\n"
                                f"수량: {qty_str}개\n"
                                f"손익: {pnl_krw:+,.0f} KRW ({pnl_pct:+.1f}%)"
                            )
                    continue
                if sl_tp == "trailing_stop":
                    order = broker.sell_market(symbol, quantity, ticker.price, reason="트레일링 스톱")
                    if order:
                        pnl_pct = (ticker.price - avg_price) / avg_price * 100 if avg_price else 0
                        pnl_krw = (ticker.price - avg_price) * quantity
                        proceeds = ticker.price * quantity
                        qty_str = f"{quantity:.8f}".rstrip("0").rstrip(".")
                        logger.warning("트레일링 스톱 매도: %s %.8f @ %s", symbol, quantity, f"{ticker.price:,.0f}")
                        update_market_snapshot(
                            symbol,
                            price=ticker.price,
                            change=ticker.change_rate * 100,
                            action="sell",
                            trade_qty=quantity,
                            trade_amount=proceeds,
                            trade_reason="트레일링 스톱",
                        )
                        if bot:
                            bot.send_message(
                                f"\U0001f7e1 <b>트레일링 스톱</b>\n"
                                f"종목: {symbol}\n"
                                f"매도금액: {proceeds:,.0f} KRW\n"
                                f"체결가격: {ticker.price:,.0f} KRW\n"
                                f"매수평단: {avg_price:,.0f} KRW\n"
                                f"수량: {qty_str}개\n"
                                f"손익: {pnl_krw:+,.0f} KRW ({pnl_pct:+.1f}%)"
                            )
                    continue

        regime_info = None
        if regime_detector and len(candles) >= regime_detector.required_candle_count():
            regime_info = regime_detector.detect(candles)
            logger.info(
                "시장 국면: %s (ADX=%.1f, 매매가중치=%.1f)",
                regime_info["regime"],
                regime_info["adx"],
                regime_info["trade_weight"],
            )

        if hasattr(strategy, "regime") and regime_info:
            strategy.regime = regime_info["regime"]

        signal_result = strategy.analyze(candles)
        signal_result.symbol = symbol

        if volume_filter:
            signal_result = volume_filter.apply(signal_result, candles)

        logger.info(
            "[%s] %s — %s (신뢰도: %.0f%%, RSI: %s)",
            signal_result.action.upper(),
            symbol,
            signal_result.reason,
            signal_result.confidence * 100,
            signal_result.indicators.get("rsi", "N/A"),
        )

        with signal_lock:
            prev = last_signals.get(symbol)
            if prev == signal_result.action and signal_result.action != "hold":
                logger.info("중복 시그널 스킵: %s → %s", symbol, signal_result.action)
                continue
            if signal_result.action == "hold":
                last_signals.pop(symbol, None)

        snap_qty = 0.0
        snap_amount = 0.0

        if broker and signal_result.action == "buy":
            if signal_result.confidence < settings.min_confidence:
                logger.info(
                    "신뢰도 부족 차단: %s confidence=%.2f < threshold=%.2f",
                    symbol, signal_result.confidence, settings.min_confidence,
                )
                continue
            if cooldown:
                can, reason = cooldown.can_trade(symbol)
                if not can:
                    logger.info("쿨다운 차단: %s — %s", symbol, reason)
                    continue

            if risk_guard:
                balance_krw = broker.get_balance_krw()
                positions = broker.get_positions()
                active_positions = sum(1 for p in positions.values() if p.quantity > 0)
                already_holding = broker.is_holding(symbol)
                check = risk_guard.check_buy(
                    symbol,
                    settings.max_order_amount_krw,
                    balance_krw=balance_krw,
                    active_positions=active_positions,
                    already_holding=already_holding,
                )
                if not check.allowed:
                    logger.warning("매수 차단: %s — %s", symbol, check.reason)
                    if bot and bot.should_notify("risk_blocked"):
                        bot.send_message(f"\u26a0\ufe0f <b>매수 차단</b>\n{symbol}: {check.reason}")
                    continue

            if regime_info and regime_info["trade_weight"] < settings.min_trade_weight:
                logger.info(
                    "국면 가중치 미달 차단: %s weight=%.2f < %.2f",
                    symbol, regime_info["trade_weight"], settings.min_trade_weight,
                )
                continue

            if position_sizer:
                equity = broker.get_equity({symbol: ticker.price})
                order_amount = position_sizer.calculate(equity, signal_result.confidence)
            else:
                order_amount = settings.max_order_amount_krw

            order = broker.buy_market(symbol, order_amount, ticker.price, reason=signal_result.reason, strategy=strategy_name)
            if order:
                with signal_lock:
                    last_signals[symbol] = "buy"
                if cooldown:
                    cooldown.record_trade(symbol)
                snap_qty = order.quantity
                snap_amount = order_amount
                logger.info("매수 체결: %s %s KRW [%s]", symbol, f"{order_amount:,.0f}", settings.trade_mode)
                if bot:
                    coin_name = symbol.split("-")[1]
                    qty_str = f"{order.quantity:.8f}".rstrip("0").rstrip(".")
                    explain = explain_indicators(signal_result.indicators)
                    safe_reason = html_mod.escape(signal_result.reason)
                    bot.send_message(
                        f"\U0001f7e2 <b>매수 체결</b>\n"
                        f"종목: {symbol} ({coin_name})\n"
                        f"매수금액: {order_amount:,.0f} KRW\n"
                        f"체결가격: {ticker.price:,.0f} KRW\n"
                        f"매수수량: {qty_str}개\n"
                        f"사유: {safe_reason}\n"
                        f"\n<b>지표 해설</b>\n<pre>{html_mod.escape(explain)}</pre>"
                    )

        elif broker and signal_result.action == "sell":
            if signal_result.confidence < settings.min_confidence:
                logger.info(
                    "매도 신뢰도 부족 스킵: %s confidence=%.2f < threshold=%.2f",
                    symbol, signal_result.confidence, settings.min_confidence,
                )
                continue

            sell_qty = 0.0
            sell_avg_price = 0.0
            sell_order = None
            pos = broker.get_position(symbol)
            if pos:
                sell_qty = pos.quantity
                sell_avg_price = pos.avg_price
                sell_order = broker.sell_market(symbol, pos.quantity, ticker.price, reason=signal_result.reason, strategy=strategy_name)
                if sell_order:
                    snap_qty = sell_qty
                    snap_amount = sell_qty * ticker.price
                    logger.info("매도 체결: %s %.8f [%s]", symbol, pos.quantity, settings.trade_mode)
            else:
                logger.info("매도 시그널이지만 보유 수량 없음: %s", symbol)

            if sell_order:
                with signal_lock:
                    last_signals[symbol] = "sell"
            if sell_order and bot:
                coin_name = symbol.split("-")[1]
                qty_str = f"{sell_qty:.8f}".rstrip("0").rstrip(".")
                proceeds = sell_qty * ticker.price
                sell_pnl_pct = (ticker.price - sell_avg_price) / sell_avg_price * 100 if sell_avg_price else 0
                sell_pnl_krw = (ticker.price - sell_avg_price) * sell_qty
                explain = explain_indicators(signal_result.indicators)
                safe_reason = html_mod.escape(signal_result.reason)
                bot.send_message(
                    f"\U0001f534 <b>매도 체결</b>\n"
                    f"종목: {symbol} ({coin_name})\n"
                    f"매도금액: {proceeds:,.0f} KRW\n"
                    f"체결가격: {ticker.price:,.0f} KRW\n"
                    f"매수평단: {sell_avg_price:,.0f} KRW\n"
                    f"매도수량: {qty_str}개\n"
                    f"손익: {sell_pnl_krw:+,.0f} KRW ({sell_pnl_pct:+.1f}%)\n"
                    f"사유: {safe_reason}"
                )

        update_market_snapshot(
            symbol,
            price=ticker.price,
            change=ticker.change_rate * 100,
            rsi=signal_result.indicators.get("rsi"),
            action=signal_result.action,
            regime=regime_info["regime"] if regime_info else "N/A",
            adx=regime_info["adx"] if regime_info else 0,
            weight=regime_info["trade_weight"] if regime_info else 1.0,
            trade_qty=snap_qty,
            trade_amount=snap_amount,
            indicators=signal_result.indicators,
            confidence=signal_result.confidence,
            trade_reason=signal_result.reason if snap_qty > 0 else "",
        )

        already_executed = snap_qty > 0
        if bot and signal_result.action != "hold" and not already_executed and bot.should_notify("signal"):
            if not (cmd_handler and cmd_handler.muted):
                bot.send_signal(signal_result, price=ticker.price)
            else:
                logger.info("알림 음소거 중 — 시그널 전송 생략")
        elif bot and signal_result.action == "hold":
            logger.info("관망 시그널 — 텔레그램 전송 생략")

    market_snapshots.pop("_live_balances", None)

    if broker is not None:
        prices = {sym: snap["price"] for sym, snap in market_snapshots.items() if isinstance(snap, dict) and "price" in snap}
        for pos_symbol, pos in broker.get_positions().items():
            if pos.quantity > 0 and pos_symbol not in prices:
                try:
                    pos_ticker = client.get_ticker(pos_symbol)
                    prices[pos_symbol] = pos_ticker.price
                except Exception:
                    logger.warning("보유 종목 가격 조회 실패: %s", pos_symbol)

        summary = broker.summary_text(prices)
        market_lines = []
        for sym, snap in market_snapshots.items():
            rsi_val = f"{snap['rsi']:.1f}" if snap["rsi"] else "N/A"
            market_lines.append(f"{sym}: RSI={rsi_val} | {snap['regime']}(ADX={snap['adx']:.0f}) | {snap['change']:+.1f}%")
        market_text = "\n".join(market_lines)

        logger.info("=== Paper Trading 현황 ===")
        for line in summary.splitlines():
            logger.info("%s", line)

        if bot:
            cycle_trades_lines = []
            for sym, snap in market_snapshots.items():
                if snap["action"] == "buy" and snap.get("trade_qty", 0) > 0:
                    qty_str = f"{snap['trade_qty']:.8f}".rstrip("0").rstrip(".")
                    cycle_trades_lines.append(
                        f"  \U0001f7e2 <b>{sym.split('-')[1]}</b> 매수 — "
                        f"{snap['trade_amount']:,.0f}원 / {qty_str}개 @ {snap['price']:,.0f}원"
                    )
                elif snap["action"] == "sell" and snap.get("trade_qty", 0) > 0:
                    qty_str = f"{snap['trade_qty']:.8f}".rstrip("0").rstrip(".")
                    cycle_trades_lines.append(
                        f"  \U0001f534 <b>{sym.split('-')[1]}</b> 매도 — "
                        f"{snap['trade_amount']:,.0f}원 / {qty_str}개 @ {snap['price']:,.0f}원"
                    )

            if cycle_trades_lines and bot.should_notify("cycle_summary"):
                msg_parts = ["\U0001f4b0 <b>Paper Trading 현황</b>"]
                msg_parts.append("\n\U0001f4dd <b>이번 주기 거래</b>")
                msg_parts.extend(cycle_trades_lines)
                msg_parts.append(f"\n<pre>{html_mod.escape(summary)}</pre>")
                msg_parts.append(f"\n\U0001f4ca <b>시장 상태</b>\n<pre>{html_mod.escape(market_text)}</pre>")
                bot.send_message("\n".join(msg_parts))


def strategy_job(
    client,
    bot,
    broker,
    risk_guard,
    symbols: list[str],
    settings,
    *,
    logger: logging.Logger,
    health,
    run_strategy_fn: Callable[..., None],
) -> None:
    """Scheduler-safe wrapper around strategy execution."""
    try:
        run_strategy_fn(client, bot, broker, risk_guard, symbols, settings)
        if health:
            health.record_success()
    except Exception:
        logger.exception("전략 실행 중 에러 발생 — 이번 주기 스킵")
        if health:
            health.record_failure()


def price_monitor_job(
    client,
    bot,
    broker,
    risk_guard,
    symbols: list[str],
    *,
    logger: logging.Logger,
    update_market_snapshot: Callable[..., None],
) -> None:
    """Poll held positions for stop-loss / take-profit events."""
    if not broker or not risk_guard:
        return

    for symbol in symbols:
        pos = broker.get_position(symbol)
        if not pos or pos.quantity <= 0 or pos.avg_price <= 0:
            continue

        try:
            ticker = client.get_ticker(symbol)
        except Exception:
            logger.warning("가격 모니터링 조회 실패: %s", symbol)
            continue

        update_market_snapshot(symbol, price=ticker.price)

        sl_tp = risk_guard.check_stop_loss_take_profit(symbol, pos.avg_price, pos.quantity, ticker.price)
        if not sl_tp:
            continue

        avg_price = pos.avg_price
        quantity = pos.quantity
        pnl_pct = (ticker.price - avg_price) / avg_price * 100
        pnl_krw = (ticker.price - avg_price) * quantity
        proceeds = ticker.price * quantity
        qty_str = f"{quantity:.8f}".rstrip("0").rstrip(".")

        trigger_labels = {
            "stop_loss": ("\U0001f534", "손절 매도", "손절 트리거"),
            "take_profit": ("\U0001f7e2", "익절 매도", "익절 트리거"),
            "trailing_stop": ("\U0001f7e1", "트레일링 스톱", "트레일링 스톱"),
        }
        emoji, label, reason = trigger_labels[sl_tp]

        order = broker.sell_market(symbol, quantity, ticker.price, reason=reason)
        if order:
            logger.warning("%s 실행: %s %.8f @ %s", label, symbol, quantity, f"{ticker.price:,.0f}")
            update_market_snapshot(
                symbol,
                price=ticker.price,
                action="sell",
                trade_qty=quantity,
                trade_amount=proceeds,
                trade_reason=reason,
            )
            if bot:
                bot.send_message(
                    f"{emoji} <b>{label}</b>\n"
                    f"종목: {symbol}\n"
                    f"매도금액: {proceeds:,.0f} KRW\n"
                    f"체결가격: {ticker.price:,.0f} KRW\n"
                    f"매수평단: {avg_price:,.0f} KRW\n"
                    f"수량: {qty_str}개\n"
                    f"손익: {pnl_krw:+,.0f} KRW ({pnl_pct:+.1f}%)"
                )


def make_ws_price_callback(
    broker,
    risk_guard,
    bot,
    *,
    logger: logging.Logger,
    update_market_snapshot: Callable[..., None],
) -> Callable[[str, float, dict], None]:
    """Create the realtime stop-trigger callback used by PriceStream."""

    def on_price(symbol: str, price: float, data: dict):
        del data
        update_market_snapshot(symbol, price=price)
        pos = broker.get_position(symbol)
        if not pos or pos.quantity <= 0 or pos.avg_price <= 0:
            return

        sl_tp = risk_guard.check_stop_loss_take_profit(symbol, pos.avg_price, pos.quantity, price)
        if not sl_tp:
            return

        avg_price = pos.avg_price
        quantity = pos.quantity
        pnl_pct = (price - avg_price) / avg_price * 100
        pnl_krw = (price - avg_price) * quantity
        proceeds = price * quantity
        qty_str = f"{quantity:.8f}".rstrip("0").rstrip(".")

        trigger_labels = {
            "stop_loss": ("\U0001f534", "손절 매도", "손절 트리거(WS)"),
            "take_profit": ("\U0001f7e2", "익절 매도", "익절 트리거(WS)"),
            "trailing_stop": ("\U0001f7e1", "트레일링 스톱", "트레일링 스톱(WS)"),
        }
        emoji, label, reason = trigger_labels[sl_tp]

        order = broker.sell_market(symbol, quantity, price, reason=reason)
        if order:
            logger.warning("[WS] %s 실행: %s %.8f @ %s", label, symbol, quantity, f"{price:,.0f}")
            update_market_snapshot(
                symbol,
                price=price,
                action="sell",
                trade_qty=quantity,
                trade_amount=proceeds,
                trade_reason=reason,
            )
            if bot:
                bot.send_message(
                    f"{emoji} <b>{label}</b> (실시간)\n"
                    f"종목: {symbol}\n"
                    f"매도금액: {proceeds:,.0f} KRW\n"
                    f"체결가격: {price:,.0f} KRW\n"
                    f"매수평단: {avg_price:,.0f} KRW\n"
                    f"수량: {qty_str}개\n"
                    f"손익: {pnl_krw:+,.0f} KRW ({pnl_pct:+.1f}%)"
                )

    return on_price
