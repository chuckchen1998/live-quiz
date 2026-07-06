"""倒计时器 — 基于 asyncio"""

import asyncio
import time
from typing import Callable, Optional


class CountdownTimer:
    """可暂停/恢复的倒计时器"""

    def __init__(self, seconds: int, on_tick: Optional[Callable[[int], None]] = None):
        self.total = seconds
        self.remaining = seconds
        self._running = False
        self._paused = False
        self._task: Optional[asyncio.Task] = None
        self.on_tick = on_tick  # 每秒回调 remaining→int

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> int:
        """启动倒计时，阻塞直到结束，返回剩余秒数(0=正常结束)"""
        self._running = True
        self._paused = False
        self.remaining = self.total

        while self.remaining > 0 and self._running:
            tick_start = time.monotonic()
            if self.on_tick:
                result = self.on_tick(self.remaining)
                if asyncio.iscoroutine(result):
                    await result
            await asyncio.sleep(1)
            elapsed = time.monotonic() - tick_start
            self.remaining -= 1
            # 补偿睡眠偏差（最多累加1秒）
            if elapsed > 1.1:
                self.remaining -= int(elapsed - 1)

        self._running = False
        return self.remaining

    def stop(self):
        """提前终止倒计时"""
        self._running = False
