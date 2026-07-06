"""抖音直播评论源 — 通过 WebSocket 连接抖音直播间获取实时评论

连接方式:
  主: WebSocket 连接抖音直播推流服务器 (低延迟, 推荐)
  备: HTTP 长轮询 (兜底)

前置条件:
  - 抖音直播间 room_id
  - Cookie (从已登录抖音的浏览器中获取)
  - 直播间需开启且允许弹幕

配置 (环境变量):
  QUIZ_DOUYIN_ROOM_ID   — 直播间 ID
  QUIZ_DOUYIN_COOKIE    — 抖音 Cookie 字符串

数据格式参考 (抖音 WebSocket 消息):
  {
    "type": "chat",
    "user": {
      "unique_id": "123456789",
      "nickname": "观众A"
    },
    "content": "B",
    "create_time": 1750000000
  }
"""

import asyncio
import json
import logging
import time
from typing import Optional

from .base import CommentEvent, CommentSource

logger = logging.getLogger(__name__)

# TODO: 抖音 WebSocket 服务器地址 (可能随版本更新)
_DOUYIN_WS_URL = "wss://webcast.douyin.com/webcast/im/push/v2/"
_DOUYIN_HTTP_URL = "https://webcast.douyin.com/webcast/im/fetch/"


class DouyinCommentSource(CommentSource):
    """抖音直播评论源 — Phase 2 空壳，Phase 3 填充真实抓取"""

    PLATFORM = "douyin"

    def __init__(self, room_id: str = "", cookie: str = ""):
        if not room_id:
            raise ValueError("缺少 room_id，请设置 QUIZ_DOUYIN_ROOM_ID 环境变量")
        if not cookie:
            raise ValueError("缺少 cookie，请设置 QUIZ_DOUYIN_COOKIE 环境变量")

        self._room_id = room_id
        self._cookie = cookie
        self._connected = False

        # WebSocket / HTTP 连接对象 (Phase 3 实现)
        self._ws = None
        self._ws_task: Optional[asyncio.Task] = None

        # 事件缓冲区
        self._queue: asyncio.Queue[CommentEvent] = asyncio.Queue(maxsize=1000)

        # 统计
        self._messages_received = 0
        self._messages_parsed = 0
        self._parse_errors = 0

    # ── 生命周期 ──

    async def connect(self) -> bool:
        """建立抖音直播间连接

        Returns:
            True=连接成功, False=失败

        TODO (Phase 3):
            1. 建立 WebSocket 连接到 _DOUYIN_WS_URL
            2. 发送握手消息 (含 room_id, cookie)
            3. 启动 _ws_loop() 后台任务接收消息
            4. 若 WebSocket 失败，降级到 HTTP 长轮询
        """
        logger.info(f"DouyinCommentSource.connect() — room_id={self._room_id}")

        # Phase 2: 模拟成功连接 (不实际建立连接)
        self._connected = True
        self._ws_task = asyncio.create_task(self._ws_loop())
        logger.info("抖音评论源已连接 (空壳模式 — 无真实数据)")
        return True

    async def disconnect(self):
        """断开连接，释放资源"""
        logger.info("DouyinCommentSource.disconnect()")
        self._connected = False

        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None

        # TODO (Phase 3): 关闭 WebSocket 连接

    async def health_check(self) -> bool:
        """健康检查"""
        if not self._connected:
            return False
        # TODO (Phase 3): ping WebSocket / HTTP HEAD
        return self._connected

    # ── 数据获取 ──

    async def get_comment(self) -> Optional[CommentEvent]:
        """获取一条评论 (非阻塞)"""
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
            "room_id": self._room_id,
            "messages_received": self._messages_received,
            "messages_parsed": self._messages_parsed,
            "parse_errors": self._parse_errors,
            "queue_size": self._queue.qsize(),
        }

    # ── 内部: WebSocket 消息循环 (Phase 2: 空壳) ──

    async def _ws_loop(self):
        """WebSocket 消息接收循环

        TODO (Phase 3):
            1. 从 WebSocket 接收原始消息
            2. 解析 JSON
            3. 过滤出 type='chat' 的消息
            4. 调用 _parse_raw() 转换为 CommentEvent
            5. 放入 _queue
            6. 处理连接断开 → 自动重连
        """
        logger.info("_ws_loop 已启动 (空壳模式)")

        # Phase 2: 空壳 — 不产生任何事件
        # Phase 3: 替换为真实的 WebSocket recv 循环
        while self._connected:
            await asyncio.sleep(1)

        logger.info("_ws_loop 已退出")

    # ── 内部: 数据解析 ──

    def _parse_raw(self, raw: dict) -> Optional[CommentEvent]:
        """将抖音原始消息转换为 CommentEvent

        Args:
            raw: 抖音 WebSocket 推送的原始 JSON

        Returns:
            CommentEvent | None (解析失败返回 None)

        抖音消息格式 (参考):
            {
                "type": "chat",
                "user": {
                    "unique_id": "xxx",    # 用户唯一 ID
                    "nickname": "观众A"     # 显示昵称
                },
                "content": "B",            # 评论内容
                "create_time": 1750000000  # Unix 时间戳
            }
        """
        self._messages_received += 1

        try:
            # 只处理聊天消息
            if raw.get("type") != "chat":
                return None

            user = raw.get("user", {})
            content = raw.get("content", "").strip()
            timestamp = raw.get("create_time", time.time())

            if not content or not user:
                return None

            # 提取答案 (A/B/C/1/2/3)
            answer = None
            upper = content.upper()
            if len(upper) <= 3:
                # 纯字母/数字 → 可能是答案
                for ch in upper:
                    if ch in "ABCD123":
                        answer = upper
                        break

            event = CommentEvent(
                user_id=str(user.get("unique_id", "")),
                nickname=str(user.get("nickname", "观众")),
                content=content,
                answer=answer,
                platform=self.PLATFORM,
                timestamp=float(timestamp),
                raw=raw,
            )

            self._messages_parsed += 1
            return event

        except Exception:
            self._parse_errors += 1
            logger.warning("解析抖音消息失败", exc_info=True)
            return None

    async def _enqueue(self, event: CommentEvent):
        """放入内部队列"""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()  # 丢弃最旧
                self._queue.put_nowait(event)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass
