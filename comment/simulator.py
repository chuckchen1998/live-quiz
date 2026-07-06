"""模拟评论数据源 — 用于开发测试"""

import asyncio
import random
from typing import Optional

from .base import Comment, CommentSource


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

    def __init__(self, correct_rate: float = 0.65, interval: float = 0.3):
        self.correct_rate = correct_rate
        self.interval = interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._queue: asyncio.Queue[Comment] = asyncio.Queue()

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._generate())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def get_comment(self) -> Optional[Comment]:
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def _generate(self):
        """后台生成模拟评论"""
        while self._running:
            name = random.choice(_NAMES)

            # 按 correct_rate 概率发送带答案的评论，其余发噪声
            if random.random() < self.correct_rate:
                answer = random.choice(["A", "B", "C", "1", "2", "3"])
                text = answer
            else:
                answer = None
                text = random.choice(_NOISE)

            comment = Comment(user=name, text=text, answer=answer)
            await self._queue.put(comment)
            await asyncio.sleep(self.interval * random.uniform(0.5, 1.5))
