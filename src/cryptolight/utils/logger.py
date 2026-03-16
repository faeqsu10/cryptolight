import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

# 토큰/키 마스킹 패턴
_SENSITIVE_PATTERNS = [
    (re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE), r"\1***REDACTED***"),
    (re.compile(r"(token[=:]\s*)['\"]?[A-Za-z0-9\-._~+/]{10,}['\"]?", re.IGNORECASE), r"\1***REDACTED***"),
    (re.compile(r"(key[=:]\s*)['\"]?[A-Za-z0-9\-._~+/]{10,}['\"]?", re.IGNORECASE), r"\1***REDACTED***"),
    (re.compile(r"(bot)[A-Za-z0-9:_\-]{30,}"), r"\1***REDACTED***"),
]


class RedactingFormatter(logging.Formatter):
    """민감 정보(토큰, API 키)를 마스킹하는 포매터."""

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        for pattern, replacement in _SENSITIVE_PATTERNS:
            msg = pattern.sub(replacement, msg)
        return msg


def setup_logger(
    name: str = "cryptolight",
    level: str = "INFO",
    log_file: str = "",
) -> logging.Logger:
    logger = logging.getLogger(name)

    if logger.handlers:
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    fmt = RedactingFormatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT)

    # 콘솔 핸들러
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # 파일 핸들러 (설정 시)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            str(log_path), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)

    return logger
