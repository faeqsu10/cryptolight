"""헬스체크 — 봇 상태 모니터링"""

import time
from dataclasses import dataclass


@dataclass
class HealthStatus:
    alive: bool = True
    last_strategy_run: float = 0.0
    last_strategy_success: bool = True
    consecutive_errors: int = 0
    uptime_seconds: float = 0.0
    total_cycles: int = 0

    def to_dict(self) -> dict:
        return {
            "alive": self.alive,
            "last_strategy_run_ago": f"{time.time() - self.last_strategy_run:.0f}s" if self.last_strategy_run else "never",
            "last_strategy_success": self.last_strategy_success,
            "consecutive_errors": self.consecutive_errors,
            "uptime_seconds": f"{self.uptime_seconds:.0f}",
            "total_cycles": self.total_cycles,
        }


class HealthMonitor:
    """봇 실행 상태를 추적한다."""

    def __init__(self):
        self._start_time = time.time()
        self._status = HealthStatus()

    def record_success(self):
        self._status.last_strategy_run = time.time()
        self._status.last_strategy_success = True
        self._status.consecutive_errors = 0
        self._status.total_cycles += 1

    def record_failure(self):
        self._status.last_strategy_run = time.time()
        self._status.last_strategy_success = False
        self._status.consecutive_errors += 1
        self._status.total_cycles += 1

    def get_status(self) -> HealthStatus:
        self._status.uptime_seconds = time.time() - self._start_time
        return self._status

    def is_healthy(self, max_consecutive_errors: int = 5, max_idle_seconds: int = 600) -> bool:
        """봇이 건강한지 확인한다."""
        if self._status.consecutive_errors >= max_consecutive_errors:
            return False
        if self._status.last_strategy_run > 0:
            idle = time.time() - self._status.last_strategy_run
            if idle > max_idle_seconds:
                return False
        return True

    def summary_text(self) -> str:
        status = self.get_status()
        uptime_min = status.uptime_seconds / 60
        lines = [
            f"상태: {'정상' if self.is_healthy() else '이상'}",
            f"가동 시간: {uptime_min:.0f}분",
            f"총 실행: {status.total_cycles}회",
            f"연속 에러: {status.consecutive_errors}회",
        ]
        return "\n".join(lines)
