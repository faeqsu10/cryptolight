"""로거 — 토큰 마스킹 테스트"""
import logging
from pathlib import Path

from cryptolight.utils.logger import RedactingFormatter, setup_logger


def test_redact_bearer_token():
    fmt = RedactingFormatter("%(message)s")
    record = logging.LogRecord("test", logging.INFO, "", 0, "Bearer eyJhbGciOi123456789", None, None)
    result = fmt.format(record)
    assert "eyJhbGciOi123456789" not in result
    assert "REDACTED" in result


def test_redact_token_value():
    fmt = RedactingFormatter("%(message)s")
    record = logging.LogRecord("test", logging.INFO, "", 0, "token=abc123def456ghi789", None, None)
    result = fmt.format(record)
    assert "abc123def456ghi789" not in result
    assert "REDACTED" in result


def test_redact_key_value():
    fmt = RedactingFormatter("%(message)s")
    record = logging.LogRecord("test", logging.INFO, "", 0, "key=MySecretAccessKey12345", None, None)
    result = fmt.format(record)
    assert "MySecretAccessKey12345" not in result
    assert "REDACTED" in result


def test_no_false_positive():
    fmt = RedactingFormatter("%(message)s")
    record = logging.LogRecord("test", logging.INFO, "", 0, "KRW-BTC 현재가: 100,000 KRW", None, None)
    result = fmt.format(record)
    assert "KRW-BTC" in result
    assert "100,000" in result
    assert "REDACTED" not in result


def test_child_logger_uses_parent_handler_and_file(tmp_path: Path):
    log_path = tmp_path / "cryptolight.log"
    parent_name = "cryptolight.testlogger"
    parent = setup_logger(parent_name, level="INFO", log_file=str(log_path))
    child = logging.getLogger(f"{parent_name}.child")

    try:
        child.info("child logger message")
        for handler in parent.handlers:
            handler.flush()

        text = log_path.read_text(encoding="utf-8")
        assert "child logger message" in text
        assert f"{parent_name}.child" in text
    finally:
        for handler in list(parent.handlers):
            handler.close()
            parent.removeHandler(handler)
