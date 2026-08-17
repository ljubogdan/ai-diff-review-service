from __future__ import annotations

import asyncio
import math
import time
from collections import deque


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.timestamps: deque[float] = deque()
        self.lock = asyncio.Lock()

    async def acquire(self) -> tuple[bool, int]:
        now = time.monotonic()
        async with self.lock:
            cutoff = now - self.window_seconds
            while self.timestamps and self.timestamps[0] <= cutoff:
                self.timestamps.popleft()
            if len(self.timestamps) >= self.limit:
                retry_after = max(1, math.ceil(self.window_seconds - (now - self.timestamps[0])))
                return False, retry_after
            self.timestamps.append(now)
            return True, 0
