"""Small in-process guards for the public Streamlit demo."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from threading import Lock


class SlidingWindowRateLimiter:
    """Thread-safe fixed-capacity sliding window.

    The limiter protects one Streamlit process from becoming an unrestricted
    proxy for server-side API credentials. It is deliberately in-memory: a
    process restart clears the window, while no visitor identifiers are stored.
    """

    def __init__(
        self,
        max_events: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(max_events, bool) or not isinstance(max_events, int) or max_events < 1:
            raise ValueError("max_events must be a positive integer")
        if isinstance(window_seconds, bool) or window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.max_events = max_events
        self.window_seconds = float(window_seconds)
        self.clock = clock
        self._events: deque[float] = deque()
        self._lock = Lock()

    def acquire(self) -> float:
        """Reserve a slot, returning zero or seconds until one is available."""

        with self._lock:
            now = self.clock()
            cutoff = now - self.window_seconds
            while self._events and self._events[0] <= cutoff:
                self._events.popleft()
            if len(self._events) >= self.max_events:
                return max(0.0, self.window_seconds - (now - self._events[0]))
            self._events.append(now)
            return 0.0
