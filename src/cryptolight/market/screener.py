"""종목 자동 스크리닝 파이프라인 — 거래량 → 백테스트 검증 → 상관관계 필터"""

import logging
import statistics
from dataclasses import dataclass, field

from cryptolight.backtest.engine import BacktestEngine
from cryptolight.exchange.base import Candle
from cryptolight.strategy import create_strategy

logger = logging.getLogger("cryptolight.market.screener")


@dataclass
class ScreeningResult:
    """스크리닝 결과."""
    selected: list[str]  # 최종 선정 종목
    candidates: list[str]  # 거래량 상위 후보
    backtest_passed: list[str]  # 백테스트 통과 종목
    backtest_details: dict[str, dict] = field(default_factory=dict)  # 종목별 백테스트 결과
    correlation_removed: list[str] = field(default_factory=list)  # 상관관계로 제외된 종목


def backtest_filter(
    candles_by_symbol: dict[str, list[Candle]],
    strategy_name: str = "score",
    min_sharpe: float = 0.0,
    initial_balance: float = 1_000_000,
    order_amount: float = 50_000,
    candle_interval: str = "day",
) -> tuple[list[str], dict[str, dict]]:
    """백테스트를 실행하여 최소 Sharpe ratio 이상인 종목만 반환한다.

    Returns:
        (통과 종목 리스트, 종목별 상세 결과 dict)
    """
    passed = []
    details: dict[str, dict] = {}

    for symbol, candles in candles_by_symbol.items():
        strategy = create_strategy(strategy_name)
        engine = BacktestEngine(
            strategy=strategy,
            initial_balance=initial_balance,
            order_amount=order_amount,
            candle_interval=candle_interval,
        )

        if len(candles) < strategy.required_candle_count() + 10:
            logger.warning("백테스트 스킵 (%s): 캔들 부족 (%d개)", symbol, len(candles))
            details[symbol] = {"skipped": True, "reason": "캔들 부족"}
            continue

        result = engine.run(candles)
        detail = {
            "sharpe": result.sharpe_ratio,
            "return_pct": result.total_return_pct,
            "max_drawdown_pct": result.max_drawdown_pct,
            "total_trades": result.total_trades,
            "win_rate": result.win_rate,
            "passed": result.sharpe_ratio >= min_sharpe,
        }
        details[symbol] = detail

        if result.sharpe_ratio >= min_sharpe:
            passed.append(symbol)
            logger.info(
                "백테스트 통과: %s (Sharpe=%.4f, 수익률=%.2f%%, 거래=%d회)",
                symbol, result.sharpe_ratio, result.total_return_pct, result.total_trades,
            )
        else:
            logger.info(
                "백테스트 탈락: %s (Sharpe=%.4f < %.4f)",
                symbol, result.sharpe_ratio, min_sharpe,
            )

    return passed, details


def calculate_returns(candles: list[Candle]) -> list[float]:
    """캔들 데이터에서 일별 수익률을 계산한다."""
    if len(candles) < 2:
        return []
    closes = [c.close for c in candles]
    return [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]


def pearson_correlation(x: list[float], y: list[float]) -> float:
    """두 수익률 시리즈의 피어슨 상관계수를 계산한다."""
    n = min(len(x), len(y))
    if n < 5:
        return 0.0

    x = x[-n:]
    y = y[-n:]

    mean_x = statistics.mean(x)
    mean_y = statistics.mean(y)

    numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    denom_x = sum((xi - mean_x) ** 2 for xi in x) ** 0.5
    denom_y = sum((yi - mean_y) ** 2 for yi in y) ** 0.5

    if denom_x == 0 or denom_y == 0:
        return 0.0

    return numerator / (denom_x * denom_y)


def correlation_filter(
    symbols: list[str],
    candles_by_symbol: dict[str, list[Candle]],
    max_correlation: float = 0.9,
    volume_ranking: dict[str, float] | None = None,
    max_positions: int = 5,
) -> tuple[list[str], list[str]]:
    """상관관계가 높은 종목 쌍에서 거래량이 낮은 종목을 제외한다.

    Args:
        symbols: 후보 종목 리스트 (거래량 순 정렬 가정)
        candles_by_symbol: 종목별 캔들 데이터
        max_correlation: 최대 허용 상관계수
        volume_ranking: 종목별 거래대금 (없으면 symbols 순서 사용)
        max_positions: 최대 보유 종목 수

    Returns:
        (선정 종목, 제외된 종목)
    """
    if len(symbols) <= 1:
        return symbols[:max_positions], []

    # 수익률 계산
    returns_map: dict[str, list[float]] = {}
    for sym in symbols:
        if sym in candles_by_symbol:
            returns_map[sym] = calculate_returns(candles_by_symbol[sym])

    # 거래량 기준 정렬 (높은 순)
    if volume_ranking:
        sorted_symbols = sorted(symbols, key=lambda s: volume_ranking.get(s, 0), reverse=True)
    else:
        sorted_symbols = list(symbols)

    selected = []
    removed = []

    for sym in sorted_symbols:
        if sym not in returns_map or len(returns_map[sym]) < 5:
            selected.append(sym)
            continue

        # 이미 선정된 종목들과 상관관계 체크
        too_correlated = False
        for existing in selected:
            if existing not in returns_map or len(returns_map[existing]) < 5:
                continue
            corr = pearson_correlation(returns_map[sym], returns_map[existing])
            if abs(corr) >= max_correlation:
                logger.info(
                    "상관관계 필터: %s ↔ %s (r=%.4f >= %.2f) → %s 제외",
                    sym, existing, corr, max_correlation, sym,
                )
                too_correlated = True
                break

        if too_correlated:
            removed.append(sym)
        else:
            selected.append(sym)

    return selected[:max_positions], removed


def run_screening_pipeline(
    client,
    strategy_name: str = "score",
    quote: str = "KRW",
    top_limit: int = 10,
    min_volume_krw: float = 10_000_000_000,
    min_sharpe: float = 0.0,
    max_correlation: float = 0.9,
    max_positions: int = 5,
    backtest_candle_count: int = 200,
    candle_interval: str = "day",
) -> ScreeningResult:
    """전체 스크리닝 파이프라인 실행.

    1. 거래량 상위 종목 조회
    2. 백테스트 검증
    3. 상관관계 필터
    """
    # Stage 2: 거래량 스크리닝
    candidates = client.get_top_volume_symbols(
        quote=quote, limit=top_limit, min_volume_krw=min_volume_krw,
    )
    logger.info("거래량 스크리닝 후보: %s (%d개)", candidates, len(candidates))

    if not candidates:
        return ScreeningResult(selected=[], candidates=[], backtest_passed=[])

    # 캔들 데이터 수집 (백테스트 + 상관관계용)
    candles_by_symbol: dict[str, list[Candle]] = {}
    for sym in candidates:
        try:
            candles = client.get_candles(sym, interval=candle_interval, count=backtest_candle_count)
            candles_by_symbol[sym] = candles
        except Exception:
            logger.warning("캔들 조회 실패: %s", sym, exc_info=True)

    # Stage 3: 백테스트 검증
    backtest_passed, backtest_details = backtest_filter(
        candles_by_symbol={s: c for s, c in candles_by_symbol.items() if s in candidates},
        strategy_name=strategy_name,
        min_sharpe=min_sharpe,
        candle_interval=candle_interval,
    )
    logger.info("백테스트 통과: %s (%d개)", backtest_passed, len(backtest_passed))

    # Stage 4: 상관관계 필터
    # 거래량 순위 = candidates 순서
    volume_ranking = {sym: len(candidates) - i for i, sym in enumerate(candidates)}
    selected, correlation_removed = correlation_filter(
        symbols=backtest_passed,
        candles_by_symbol=candles_by_symbol,
        max_correlation=max_correlation,
        volume_ranking=volume_ranking,
        max_positions=max_positions,
    )
    logger.info("최종 선정: %s (%d개, 상관관계 제외: %s)", selected, len(selected), correlation_removed)

    return ScreeningResult(
        selected=selected,
        candidates=candidates,
        backtest_passed=backtest_passed,
        backtest_details=backtest_details,
        correlation_removed=correlation_removed,
    )
