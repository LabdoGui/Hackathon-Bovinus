"""Limitação de tentativas com chave de API inválida (em memória, por origem)."""

import threading
import time
from collections import deque
from collections.abc import Callable

MAX_TRACKED = 10_000


class FailureLimiter:
    """Bloqueia uma origem após ``max_failures`` falhas dentro de ``window_s`` segundos."""

    def __init__(self, max_failures: int, window_s: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.max_failures = max_failures
        self.window_s = window_s
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        events = self._failures.get(key)
        if events is None:
            return deque()
        while events and now - events[0] >= self.window_s:
            events.popleft()
        if not events:
            self._failures.pop(key, None)
        return events

    def retry_after(self, key: str) -> int:
        """Segundos até poder tentar de novo; 0 se a origem não está bloqueada."""
        now = self._clock()
        with self._lock:
            events = self._prune(key, now)
            if len(events) < self.max_failures:
                return 0
            return max(1, int(self.window_s - (now - events[0])) + 1)

    def record_failure(self, key: str) -> None:
        now = self._clock()
        with self._lock:
            if len(self._failures) >= MAX_TRACKED and key not in self._failures:
                for stale in [k for k in self._failures if not self._prune(k, now)]:
                    self._failures.pop(stale, None)
                if len(self._failures) >= MAX_TRACKED:  # ainda cheio: descarta o mais antigo
                    self._failures.pop(next(iter(self._failures)), None)
            self._failures.setdefault(key, deque()).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
