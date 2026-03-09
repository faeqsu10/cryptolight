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
    target_symbols: str = "KRW-BTC,KRW-ETH"

    # 로깅
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def symbol_list(self) -> list[str]:
        return [s.strip() for s in self.target_symbols.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
