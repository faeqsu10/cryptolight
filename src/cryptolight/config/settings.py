from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 업비트 API
    upbit_access_key: str = ""
    upbit_secret_key: str = ""

    # 텔레그램
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_poll_timeout_seconds: int = 20
    telegram_request_timeout_seconds: int = 30
    telegram_poll_backoff_initial_seconds: float = 1.0
    telegram_poll_backoff_max_seconds: float = 30.0

    # 거래 설정
    trade_mode: Literal["paper", "live"] = "paper"
    max_order_amount_krw: int = 50_000
    absolute_max_order_krw: int = 500_000  # 하드캡: 어떤 경우에도 이 금액 초과 불가
    daily_loss_limit_krw: int = 100_000
    max_positions: int = 5
    stop_loss_pct: float = -10.0
    take_profit_pct: float = 15.0
    trailing_stop_pct: float = 0.0  # >0이면 트레일링 스톱 활성화 (예: 3.0 = 고점 대비 -3%)
    target_symbols: str = "KRW-BTC,KRW-ETH"

    # 스케줄러
    schedule_interval_minutes: int = 60
    price_monitor_interval_minutes: int = 5  # 손절/익절 가격 모니터링 주기
    command_poll_seconds: int = 5
    paper_initial_balance: float = 1_000_000
    db_path: str = "data/trades.db"

    # 알림
    surge_alert_threshold: float = 0.05  # 5% 이상 변동 시 알림
    notification_level: str = "normal"  # silent | minimal | normal | verbose

    # 전략
    strategy_name: str = "score"  # rsi | macd | bollinger | volatility_breakout | ensemble | score
    ensemble_strategies: str = "rsi,macd,bollinger"  # 앙상블에 사용할 전략 목록
    min_confidence: float = 0.3  # 최소 신뢰도 — 이 미만이면 주문 차단
    min_trade_weight: float = 0.3  # 국면 가중치 최소값 — 미만이면 거래 차단
    candle_interval: str = "minute240"  # 캔들 주기: day, minute240(4시간), minute60(1시간) 등

    # 자동 종목 스크리닝
    auto_select_symbols: bool = False  # True면 거래량 상위 자동 스크리닝
    top_volume_limit: int = 10  # 거래량 상위 N개 후보
    min_daily_volume_krw: int = 10_000_000_000  # 최소 일 거래대금 (100억원)
    screening_interval_hours: int = 24  # 스크리닝 주기 (시간)
    min_backtest_sharpe: float = 0.0  # 백테스트 최소 Sharpe ratio
    max_correlation: float = 0.9  # 종목 간 최대 상관계수

    # Google AI (Gemini)
    google_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"  # Gemini 모델명
    ask_daily_limit: int = 10  # /ask 일일 사용 제한

    # 웹 대시보드
    enable_web: bool = False
    web_host: str = "127.0.0.1"
    web_port: int = 8090
    web_username: str = ""
    web_password: str = ""

    # 런타임 스케줄 / 타임존
    app_timezone: str = "Asia/Seoul"
    daily_summary_hour: int = 9
    daily_summary_minute: int = 0
    self_improvement_day_of_week: str = "sun"
    self_improvement_hour: int = 3
    self_improvement_minute: int = 0

    # 로깅
    log_level: str = "INFO"
    log_file: str = ""  # 비어있으면 파일 로깅 비활성화, 경로 지정 시 RotatingFileHandler

    # 포지션 사이징
    position_sizing_method: str = "percent"  # fixed | percent | kelly
    position_risk_pct: float = 5.0  # percent 모드: 총자산의 N%

    # 쿨다운
    trade_cooldown_seconds: int = 180  # 동일 종목 재주문 대기 (3분)
    max_orders_per_hour: int = 10  # 시간당 최대 주문 횟수

    # 캔들 캐시
    candle_cache_ttl: int = 300  # 캔들 캐시 TTL (초) — 실행 주기에 맞춰 조정

    # 거래소 수수료
    commission_rate: float = 0.0005  # 업비트 0.05%

    # 백테스트
    backtest_slippage_pct: float = 0.1  # 슬리피지 시뮬레이션 (0.1%)
    backtest_spread_pct: float = 0.05  # 스프레드 시뮬레이션 (0.05%)

    # 자동 최적화 / 자기개선 루프
    enable_auto_optimization: bool = False  # 자동 최적화 활성화
    enable_auto_parameter_tuning: bool = True  # 전략 파라미터 자동 조정
    arena_lookback_days: int = 30  # Arena 백테스트 데이터 기간
    optimizer_trials: int = 50  # 파라미터 최적화 시도 횟수
    min_sharpe_improvement: float = 0.5  # 전략 전환 최소 Sharpe 개선폭
    parameter_min_sharpe_improvement: float = 0.2  # 파라미터 조정 최소 Sharpe 개선폭
    switch_cooldown_days: int = 7  # 전략 전환 후 쿨다운 기간
    parameter_tuning_interval_hours: int = 6  # 파라미터 조정 주기
    parameter_tuning_cooldown_hours: int = 12  # 파라미터 조정 후 재조정까지 대기
    parameter_tuning_lookback_candles: int = 300  # 파라미터 조정용 캔들 수
    parameter_tuning_n_folds: int = 3  # 파라미터 조정 Walk-Forward fold 수
    parameter_tuning_min_wf_consistency: float = 66.7  # 파라미터 조정 최소 WF 일관성

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def symbol_list(self) -> list[str]:
        return [s.strip() for s in self.target_symbols.split(",") if s.strip()]

    @property
    def ensemble_strategy_list(self) -> list[str]:
        return [s.strip() for s in self.ensemble_strategies.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
