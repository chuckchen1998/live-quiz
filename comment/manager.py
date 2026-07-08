"""连接管理器 — 自动重连、健康检查、背压保护"""

import asyncio
import logging
import time
from typing import Optional, Callable, Awaitable

from .base import CommentEvent, CommentSource

logger = logging.getLogger(__name__)


class ConnectionManager:
    """管理评论源的连接生命周期

    职责:
      - 自动重连（指数退避，最多 5 次）
      - 定期健康检查（默认 30s）
      - 事件缓冲队列（背压保护，max 1000）
      - 生命周期回调通知
    """

    def __init__(
        self,
        source: CommentSource,
        *,
        max_reconnect: int = 5,
        health_interval: float = 30.0,
        queue_size: int = 1000,
    ):
        self.source = source
        self._max_reconnect = max_reconnect
        self._health_interval = health_interval
        self._queue: asyncio.Queue[CommentEvent] = asyncio.Queue(maxsize=queue_size)

        # 回调
        self.on_connected: Optional[Callable[[], Awaitable[None]]] = None
        self.on_disconnected: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_error: Optional[Callable[[Exception], Awaitable[None]]] = None
        self.on_reconnecting: Optional[Callable[[int, int], Awaitable[None]]] = None

        # 内部状态
        self._health_task: Optional[asyncio.Task] = None
        self._consume_task: Optional[asyncio.Task] = None
        self._messages_received = 0
        self._errors = 0
        self._started_at = 0.0

    # ── 生命周期 ──

    async def start(self) -> bool:
        """启动连接（含自动重连）"""
        self._started_at = time.time()
        connected = await self._connect_with_retry()
        if connected:
            self._health_task = asyncio.create_task(self._health_loop())
            self._consume_task = asyncio.create_task(self._consume_loop())
        return connected

    async def stop(self):
        """停止连接，释放资源"""
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
        if self._consume_task:
            self._consume_task.cancel()
            try:
                await self._consume_task
            except asyncio.CancelledError:
                pass
        await self.source.disconnect()

    # ── 数据获取 ──

    async def get_comment(self) -> Optional[CommentEvent]:
        """从内部缓冲区获取一条评论（非阻塞）"""
        try:
            event = self._queue.get_nowait()
            return event
        except asyncio.QueueEmpty:
            return None

    # ── 统计 ──

    def stats(self) -> dict:
        return {
            "platform": self.source.platform,
            "connected": self.source.is_connected,
            "messages_received": self._messages_received,
            "errors": self._errors,
            "uptime_seconds": int(time.time() - self._started_at) if self._started_at else 0,
            "queue_size": self._queue.qsize(),
            "queue_max": self._queue.maxsize,
        }

    # ── 内部 ──

    async def _connect_with_retry(self) -> bool:
        """指数退避重连"""
        for attempt in range(1, self._max_reconnect + 1):
            try:
                ok = await self.source.connect()
                if ok:
                    logger.info(f"已连接: {self.source.platform}")
                    if self.on_connected:
                        await self.on_connected()
                    return True
            except Exception as e:
                logger.error(f"连接失败 (attempt {attempt}/{self._max_reconnect}): {e}")
                self._errors += 1
                if self.on_error:
                    await self.on_error(e)

            if attempt < self._max_reconnect:
                delay = min(2 ** (attempt - 1), 30)
                logger.info(f"{delay}s 后重试...")
                if self.on_reconnecting:
                    await self.on_reconnecting(attempt, self._max_reconnect)
                await asyncio.sleep(delay)

        logger.error(f"重连耗尽 ({self._max_reconnect} 次)，放弃")
        if self.on_disconnected:
            await self.on_disconnected("重连次数耗尽")
        return False

    async def _health_loop(self):
        """定期健康检查"""
        while True:
            await asyncio.sleep(self._health_interval)
            try:
                ok = await self.source.health_check()
                if not ok:
                    logger.warning(f"健康检查失败: {self.source.platform}")
                    self._errors += 1
                    if self.on_disconnected:
                        await self.on_disconnected("健康检查失败")
                    await self.source.disconnect()
                    ok = await self._connect_with_retry()
                    if not ok:
                        break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"健康检查异常: {e}")
                self._errors += 1

    async def _consume_loop(self):
        """持续从评论源读取事件并放入内部队列"""
        while True:
            try:
                event = await self.source.get_comment()
                if event:
                    await self._enqueue(event)
                else:
                    await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"消费事件异常: {e}")
                self._errors += 1
                await asyncio.sleep(0.5)

    async def _enqueue(self, event: CommentEvent):
        """将事件放入内部队列（满时丢弃最旧事件）"""
        try:
            self._queue.put_nowait(event)
            self._messages_received += 1
        except asyncio.QueueFull:
            # 丢弃最旧的事件，放入新的
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(event)
                self._messages_received += 1
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass  # 极端竞争，丢弃
