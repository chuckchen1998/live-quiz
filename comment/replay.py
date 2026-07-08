"""评论回放源 — 从 JSON 文件读取真实评论并按时间戳回放

用途:
  1. 录播测试 — 用录制的真实直播评论验证系统
  2. 压力测试 — 调节 speed 参数加速回放模拟高并发
  3. CI 集成测试 — 固定数据集可复现结果

文件格式 (data/replay_comments.json):
  [
    {"user_id": "u1", "nickname": "小明", "content": "B", "answer": "B", "timestamp": 0.5},
    {"user_id": "u2", "nickname": "小红", "content": "A", "answer": "A", "timestamp": 0.8},
    ...
  ]

用法:
  source = ReplayCommentSource("data/replay_comments.json", speed=10.0)
  await source.connect()
  # 以 10x 速度回放 (1秒内回放10秒的评论量)
"""

import asyncio
import json
import logging
import time
from typing import Optional

from .base import CommentEvent, CommentSource

logger = logging.getLogger(__name__)


class ReplayCommentSource(CommentSource):
    """从文件按时间戳回放评论"""

    PLATFORM = "replay"

    def __init__(self, file_path: str = "data/replay_comments.json", speed: float = 1.0):
        """
        Args:
            file_path: 评论数据文件路径
            speed: 回放倍速 (1.0=原速, 10.0=10倍速, 0.5=半速)
        """
        self._file_path = file_path
        self._speed = max(speed, 0.01)
        self._connected = False
        self._task: Optional[asyncio.Task] = None
        self._queue: asyncio.Queue[CommentEvent] = asyncio.Queue(maxsize=5000)
        self._events: list[CommentEvent] = []
        self._play_count = 0
        self._errors = 0

    # ── 生命周期 ──

    async def connect(self) -> bool:
        try:
            with open(self._file_path, "r", encoding="utf-8") as f:
                raw = json.load(f)

            if not isinstance(raw, list):
                raise ValueError("回放文件格式错误: 需要 JSON 数组")

            self._events = []
            for item in raw:
                event = CommentEvent(
                    user_id=str(item.get("user_id", "")),
                    nickname=str(item.get("nickname", "观众")),
                    content=str(item.get("content", "")),
                    answer=item.get("answer"),
                    platform=self.PLATFORM,
                    timestamp=float(item.get("timestamp", time.time())),
                    raw=item,
                )
                self._events.append(event)

            logger.info(f"回放源加载 {len(self._events)} 条评论 (speed={self._speed}x)")
            self._connected = True
            self._task = asyncio.create_task(self._replay())
            return True

        except FileNotFoundError:
            logger.error(f"回放文件不存在: {self._file_path}")
            return False
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"回放文件解析失败: {e}")
            return False

    async def disconnect(self):
        self._connected = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def health_check(self) -> bool:
        return self._connected

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

    async def get_stats(self) -> dict:
        return {
            "platform": self.PLATFORM,
            "file": self._file_path,
            "total_events": len(self._events),
            "play_count": self._play_count,
            "speed": self._speed,
            "queue_size": self._queue.qsize(),
            "errors": self._errors,
        }

    # ── 内部 ──

    async def _replay(self):
        """按时间戳回放评论"""
        if not self._events:
            logger.warning("回放事件列表为空")
            return

        logger.info(f"开始回放 {len(self._events)} 条评论")

        # 以第一条的时间戳为基准
        t0 = self._events[0].timestamp
        loop_start = time.monotonic()

        for event in self._events:
            if not self._connected:
                break

            try:
                # 计算等待时间
                target_elapsed = (event.timestamp - t0) / self._speed
                actual_elapsed = time.monotonic() - loop_start
                wait = target_elapsed - actual_elapsed

                if wait > 0:
                    await asyncio.sleep(wait)

                # 更新时间戳为当前时间
                event.timestamp = time.time()
                await self._queue.put(event)
                self._play_count += 1

            except asyncio.CancelledError:
                break
            except Exception:
                self._errors += 1
                logger.debug("回放入队异常", exc_info=True)

        logger.info(f"回放完成: {self._play_count}/{len(self._events)} 条")
