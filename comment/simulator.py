"""模拟评论数据源 — 用于开发测试"""

import asyncio
import random
import time
import uuid
from typing import Optional

from .base import CommentEvent, CommentSource


# 模拟用户名池
_NAMES = [
    "小明", "小红", "阿强", "老张", "小美", "大壮",
    "路人甲", "吃瓜群众", "弹幕高手", "萌新一号",
    "技术宅", "程序猿", "摸鱼达人", "键盘侠", "夜猫子",
]

# 噪声评论（不含答案）
_NOISE = [
    "来了来了", "主播好", "666", "哈哈哈哈",
    "这题我会", "太难了", "好快", "前排前排",
    "冲冲冲", "学到了", "打卡", "第一",
]


class SimulatorSource(CommentSource):
    """模拟评论源：随机生成带答案和无答案评论"""

    PLATFORM = "simulator"

    def __init__(self, correct_rate: float = 0.65, interval: float = 0.3):
        self._correct_rate = correct_rate
        self._interval = interval
        self._running = False
        self._connected = False
        self._task: Optional[asyncio.Task] = None
        self._queue: asyncio.Queue[CommentEvent] = asyncio.Queue()

    # ── 生命周期 ──

    async def connect(self) -> bool:
        self._running = True
        self._task = asyncio.create_task(self._generate())
        self._connected = True
        return True

    async def disconnect(self):
        self._running = False
        self._connected = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def health_check(self) -> bool:
        return self._connected and self._task is not None and not self._task.done()

    # ── 数据获取 ──

    async def get_comment(self) -> Optional[CommentEvent]:
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    # ── 元信息 ──

    @property
    def platform(self) -> str:
        return self.PLATFORM

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── 内部生成 ──

    async def _generate(self):
        """后台生成模拟评论"""
        while self._running:
            name = random.choice(_NAMES)

            if random.random() < self._correct_rate:
                answer = random.choice(["A", "B", "C", "1", "2", "3"])
                content = answer
            else:
                answer = None
                content = random.choice(_NOISE)

            event = CommentEvent(
                user_id=str(uuid.uuid4())[:8],
                nickname=name,
                content=content,
                answer=answer,
                platform=self.PLATFORM,
                timestamp=time.time(),
            )
            await self._queue.put(event)
            await asyncio.sleep(self._interval * random.uniform(0.5, 1.5))
