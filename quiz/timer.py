"""倒计时器 — 基于 asyncio"""

import asyncio
import time
from typing import Callable, Optional


class CountdownTimer:
    """异步倒计时器，支持提前终止"""

    def __init__(self, seconds: int, on_tick: Optional[Callable[[int], None]] = None):
        self.total = seconds
        self.remaining = seconds
        self._running = False
        self.on_tick = on_tick  # 每秒回调 remaining→int

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> int:
        """启动倒计时，阻塞直到结束或 stop() 被调用
        
        Returns:
            int: 剩余秒数（0=正常结束，>0=被提前终止）
        """
        self._running = True
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
            # 补偿睡眠偏差：若实际睡眠 > 1.1s，多扣相应秒数
            if elapsed > 1.1:
                self.remaining -= int(elapsed - 1)

        self._running = False
        return max(self.remaining, 0)

    def stop(self):
        """提前终止倒计时（协程安全：仅设置标志位）"""
        self._running = False
