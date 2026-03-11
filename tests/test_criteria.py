import cryptolight.main as main_module
from cryptolight.config.settings import Settings


def test_score_criteria_includes_beginner_explanations():
    original_snapshots = dict(main_module._market_snapshots)
    try:
        main_module._market_snapshots.clear()
        main_module._market_snapshots.update({"KRW-BTC": {"regime": "sideways"}})

        settings = Settings(_env_file=None, strategy_name="score", min_confidence=0.4)
        lines = main_module._build_strategy_criteria_lines(settings)
        text = "\n".join(lines)

        assert "현재 매수/매도 기준:" in text
        assert "지표 설명:" in text
        assert "RSI: 최근 상승/하락 힘" in text
        assert "MACD: 단기와 장기 평균의 차이" in text
        assert "confidence: 봇이 신호를 얼마나 강하게 보는지" in text
        assert "횡보장: 매수 65점 이상 / 매도 55점 이상" in text
    finally:
        main_module._market_snapshots.clear()
        main_module._market_snapshots.update(original_snapshots)


def test_rsi_criteria_includes_rsi_explanation():
    settings = Settings(_env_file=None, strategy_name="rsi", min_confidence=0.4)

    lines = main_module._build_strategy_criteria_lines(settings)
    text = "\n".join(lines)

    assert "매수: RSI <= 30" in text
    assert "매도: RSI >= 70" in text
    assert "지표 설명:" in text
    assert "RSI: 최근 상승/하락 힘을 0~100으로 나타냅니다" in text
