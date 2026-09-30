"""호출 유량 제한기 - 한국투자증권 초당 호출 제한 대응.

rate_per_sec 는 config(collector.rate_per_sec)에서 온다. 단순 최소 간격 방식:
연속 호출 사이 간격이 1/rate 초 이상이 되도록 대기한다. 버스트를 허용하지 않으므로
모의(1건/초)처럼 여유가 없는 한도에서도 초과가 나지 않는다.
"""
from __future__ import annotations

import time


class RateLimiter:
    def __init__(self, rate_per_sec: float, *, clock=time.monotonic, sleep=time.sleep) -> None:
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be positive")
        self.interval = 1.0 / float(rate_per_sec)
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None:
            remaining = self.interval - (now - self._last)
            if remaining > 0:
                self._sleep(remaining)
                now = self._clock()
        self._last = now
