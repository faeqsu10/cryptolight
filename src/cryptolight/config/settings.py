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

    # 거래 설정
    trade_mode: Literal["paper", "live"] = "paper"
    max_order_amount_krw: int = 50_000
    absolute_max_order_krw: int = 500_000  # 하드캡: 어떤 경우에도 이 금액 초과 불가
    daily_loss_limit_krw: int = 100_000
    max_positions: int = 5
    stop_loss_pct: float = -5.0
    take_profit_pct: float = 10.0
    trailing_stop_pct: float = 0.0  # >0이면 트레일링 스톱 활성화 (예: 3.0 = 고점 대비 -3%)
    target_symbols: str = "KRW-BTC,KRW-ETH"

    # 스케줄러
    schedule_interval_minutes: int = 5
    command_poll_seconds: int = 30
    paper_initial_balance: float = 1_000_000
    db_path: str = "data/trades.db"

    # 알림
    surge_alert_threshold: float = 0.05  # 5% 이상 변동 시 알림

    # 전략
    strategy_name: str = "rsi"  # rsi | macd | bollinger | volatility_breakout | ensemble
    ensemble_strategies: str = "rsi,macd,bollinger"  # 앙상블에 사용할 전략 목록

    # 로깅
    log_level: str = "INFO"
    log_file: str = ""  # 비어있으면 파일 로깅 비활성화, 경로 지정 시 RotatingFileHandler

    # 백테스트
    backtest_slippage_pct: float = 0.1  # 슬리피지 시뮬레이션 (0.1%)
    backtest_spread_pct: float = 0.05  # 스프레드 시뮬레이션 (0.05%)

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
