"""模拟评论数据源 — 用于开发测试"""

import asyncio, random, time, uuid
from typing import Optional
from .base import CommentEvent, CommentSource

_NAMES = ["小明","小红","阿强","老张","小美","大壮","路人甲","吃瓜群众","弹幕高手","萌新一号","技术宅","程序猿","摸鱼达人","键盘侠","夜猫子"]
_NOISE = ["来了来了","主播好","666","哈哈哈哈","这题我会","太难了","好快","前排前排","冲冲冲","学到了","打卡","第一"]
_FAKE_ANSWER_NOISE = ["A队加油","B站报到","C位出道","ABC走一波","AB选哪个啊","我觉得A和B都行","AAAA","BBBB","C是错的吧","这题A还是B啊","1号上啊","2号选手加油","A方案","B计划","C选项不对"]

class SimulatorSource(CommentSource):
    PLATFORM = "simulator"
    def __init__(self, correct_rate: float = 0.65, interval: float = 0.3, fake_answer_rate: float = 0.15):
        self._correct_rate = max(0.0, min(1.0, correct_rate))
        self._interval = interval
        self._fake_answer_rate = max(0.0, min(1.0, fake_answer_rate))
        self._running = False; self._connected = False
        self._task: Optional[asyncio.Task] = None
        self._queue: asyncio.Queue[CommentEvent] = asyncio.Queue()

    async def connect(self) -> bool:
        self._running = True; self._task = asyncio.create_task(self._generate()); self._connected = True; return True
    async def disconnect(self):
        self._running = False; self._connected = False
        if self._task: self._task.cancel()
        try: await self._task
        except asyncio.CancelledError: pass
    async def health_check(self) -> bool: return self._connected and self._task is not None and not self._task.done()
    async def get_comment(self) -> Optional[CommentEvent]:
        try: return self._queue.get_nowait()
        except asyncio.QueueEmpty: return None
    @property
    def platform(self) -> str: return self.PLATFORM
    @property
    def is_connected(self) -> bool: return self._connected

    async def _generate(self):
        while self._running:
            name = random.choice(_NAMES)
            roll = random.random()
            if roll < self._correct_rate:
                ans = random.choice(["A","B","C","1","2","3"])
                if random.random() < 0.5: content = random.choice(["选","我选","答案是","我觉","投",""]) + ans
                else: content = ans
                answer = ans
            elif roll < self._correct_rate + self._fake_answer_rate:
                content = random.choice(_FAKE_ANSWER_NOISE); answer = None
            else:
                content = random.choice(_NOISE); answer = None
            event = CommentEvent(user_id=str(uuid.uuid4())[:8], nickname=name, content=content, answer=answer, platform=self.PLATFORM, timestamp=time.time())
            await self._queue.put(event)
            await asyncio.sleep(self._interval * random.uniform(0.5, 1.5))
