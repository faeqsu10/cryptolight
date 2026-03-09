"""HealthMonitor 헬스체크 테스트"""
from cryptolight.health import HealthMonitor


def test_initial_state():
    hm = HealthMonitor()
    status = hm.get_status()
    assert status.alive is True
    assert status.total_cycles == 0
    assert status.consecutive_errors == 0


def test_record_success():
    hm = HealthMonitor()
    hm.record_success()
    hm.record_success()
    status = hm.get_status()
    assert status.total_cycles == 2
    assert status.last_strategy_success is True
    assert status.consecutive_errors == 0


def test_record_failure():
    hm = HealthMonitor()
    hm.record_failure()
    hm.record_failure()
    status = hm.get_status()
    assert status.consecutive_errors == 2
    assert status.last_strategy_success is False


def test_error_reset_on_success():
    hm = HealthMonitor()
    hm.record_failure()
    hm.record_failure()
    hm.record_success()
    assert hm.get_status().consecutive_errors == 0


def test_is_healthy():
    hm = HealthMonitor()
    hm.record_success()
    assert hm.is_healthy() is True


def test_unhealthy_after_errors():
    hm = HealthMonitor()
    for _ in range(5):
        hm.record_failure()
    assert hm.is_healthy(max_consecutive_errors=5) is False


def test_summary_text():
    hm = HealthMonitor()
    hm.record_success()
    text = hm.summary_text()
    assert "정상" in text
    assert "총 실행" in text
