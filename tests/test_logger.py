"""로거 — 토큰 마스킹 테스트"""
import logging

from cryptolight.utils.logger import RedactingFormatter


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
