from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 업비트 API
    upbit_access_key: str = ""
    upbit_secret_key: str = ""

    # 텔레그램
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # 거래 설정
    trade_mode: str = "paper"  # paper | live
    max_order_amount_krw: int = 50_000
    daily_loss_limit_krw: int = 100_000
    max_positions: int = 5
    stop_loss_pct: float = -5.0
    take_profit_pct: float = 10.0
    target_symbols: str = "KRW-BTC,KRW-ETH"

    # 스케줄러
    schedule_interval_minutes: int = 5
    command_poll_seconds: int = 30
    paper_initial_balance: float = 1_000_000
    db_path: str = "data/trades.db"

    # 알림
    surge_alert_threshold: float = 0.05  # 5% 이상 변동 시 알림

    # 전략
    strategy_name: str = "rsi"  # rsi | volatility_breakout

    # 로깅
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def symbol_list(self) -> list[str]:
        return [s.strip() for s in self.target_symbols.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
