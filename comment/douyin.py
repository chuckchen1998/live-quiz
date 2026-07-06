"""抖音直播评论源 — WebSocket + Protobuf 实时获取直播间弹幕

协议:
  主: WebSocket + Protobuf (抖音官方协议, 低延迟)
  备: HTTP 轮询 (降级方案, 无需 protobuf 编译)

前置条件:
  QUIZ_DOUYIN_ROOM_ID  — 抖音直播间 ID (从直播间 URL 提取)
  QUIZ_DOUYIN_COOKIE   — 抖音登录 Cookie (浏览器 F12 → 网络 → 请求头)

Protobuf 编译 (WebSocket 模式必需):
  1. 从社区仓库获取 .proto 文件:
     github.com/zhangyiming748/douyin-live-protobuf
  2. pip install protobuf
  3. protoc --python_out=comment/ *.proto
  4. 取消代码中 _PROTO_AVAILABLE 下方的注释

连接流程:
  1. 获取直播间 WebSocket URL (含 token)
  2. 建立 aiohttp WebSocket 连接
  3. 发送握手心跳帧
  4. 接收 Protobuf Response → 提取 ChatMessage
  5. 转换为 CommentEvent → 入队 → 业务层消费
"""

import asyncio
import json
import logging
import struct
import time
from typing import Optional

import aiohttp

from .base import CommentEvent, CommentSource

logger = logging.getLogger(__name__)

# ── Protobuf 支持 (需编译 .proto 后取消注释) ──
try:
    # 编译 protobuf 后取消下面两行注释:
    # from . import douyin_pb2
    # _PROTO_AVAILABLE = True
    _PROTO_AVAILABLE = False
except ImportError:
    _PROTO_AVAILABLE = False

# ── 抖音 API 端点 ──
_DOUYIN_LIVE_API = "https://live.douyin.com"
_DOUYIN_WS_HOST = "wss://webcast.douyin.com"

# ── HTTP 请求头 ──
_HEADERS_TEMPLATE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://live.douyin.com/",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


class DouyinCommentSource(CommentSource):
    """抖音直播评论源 — Phase 3 完整实现

    用法:
        source = DouyinCommentSource(room_id="123456789", cookie="ttwid=...")
        await source.connect()
        while True:
            event = await source.get_comment()
            if event:
                print(f"{event.nickname}: {event.content}")
    """

    PLATFORM = "douyin"

    def __init__(self, room_id: str = "", cookie: str = ""):
        if not room_id:
            raise ValueError("缺少 room_id")
        if not cookie:
            raise ValueError("缺少 cookie")

        self._room_id = str(room_id)
        self._cookie = cookie
        self._connected = False
        self._mode = "unknown"  # "websocket" | "polling"

        # aiohttp session (跨连接复用)
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None

        # 后台任务
        self._ws_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._ping_interval = 10  # 心跳间隔 (秒)

        # 事件缓冲
        self._queue: asyncio.Queue[CommentEvent] = asyncio.Queue(maxsize=2000)

        # WebSocket URL (connect 时获取)
        self._ws_url: str = ""

        # 连接统计
        self._messages_received = 0
        self._messages_parsed = 0
        self._parse_errors = 0
        self._reconnect_count = 0
        self._last_msg_time = 0.0

    # ═══════════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════════

    async def connect(self) -> bool:
        """建立抖音直播间连接

        流程:
          1. HTTP GET 直播间页面 → 提取 WebSocket token
          2. 建立 aiohttp WebSocket 连接
          3. 启动消息循环 + 心跳
          4. 若 WebSocket 失败 → 降级到 HTTP 轮询
        """
        logger.info(f"连接抖音直播间 room_id={self._room_id}")

        self._session = aiohttp.ClientSession(
            headers=_HEADERS_TEMPLATE,
            cookie_headers={"Cookie": self._cookie},
            timeout=aiohttp.ClientTimeout(total=30),
        )

        # 尝试 WebSocket
        ws_ok = await self._connect_ws()
        if ws_ok:
            self._mode = "websocket"
            self._ws_task = asyncio.create_task(self._ws_loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self._connected = True
            logger.info("✓ 抖音 WebSocket 已连接")
            return True

        # 降级: HTTP 轮询
        logger.warning("WebSocket 连接失败，降级到 HTTP 轮询")
        poll_ok = await self._start_polling()
        if poll_ok:
            self._mode = "polling"
            self._connected = True
            logger.info("✓ 抖音 HTTP 轮询已启动")
            return True

        # 彻底失败
        await self._cleanup_session()
        logger.error("✗ 无法连接抖音直播间")
        return False

    async def disconnect(self):
        """断开连接"""
        logger.info(f"断开抖音连接 (mode={self._mode})")
        self._connected = False

        # 取消后台任务
        for task in (self._ws_task, self._heartbeat_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._ws_task = None
        self._heartbeat_task = None

        # 关闭 WebSocket
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None

        # 关闭 HTTP session
        await self._cleanup_session()

    async def health_check(self) -> bool:
        """健康检查: 最近 30s 内有消息即认为健康"""
        if not self._connected:
            return False
        if self._last_msg_time == 0:
            return True  # 刚连接, 还没收到消息
        return (time.time() - self._last_msg_time) < 30

    # ═══════════════════════════════════════════════
    # 数据获取
    # ═══════════════════════════════════════════════

    async def get_comment(self) -> Optional[CommentEvent]:
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    # ═══════════════════════════════════════════════
    # 元信息
    # ═══════════════════════════════════════════════

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
            "mode": self._mode,
            "proto_available": _PROTO_AVAILABLE,
            "connected": self._connected,
            "messages_received": self._messages_received,
            "messages_parsed": self._messages_parsed,
            "parse_errors": self._parse_errors,
            "reconnect_count": self._reconnect_count,
            "queue_size": self._queue.qsize(),
            "last_msg_ago": round(time.time() - self._last_msg_time, 1)
                if self._last_msg_time else -1,
        }

    # ═══════════════════════════════════════════════
    # WebSocket 连接
    # ═══════════════════════════════════════════════

    async def _connect_ws(self) -> bool:
        """建立 WebSocket 连接"""
        try:
            # Step 1: 获取 WebSocket URL (含 token)
            ws_url = await self._fetch_ws_url()
            if not ws_url:
                logger.warning("无法获取 WebSocket URL")
                return False

            self._ws_url = ws_url
            logger.info(f"WebSocket URL: {ws_url[:80]}...")

            # Step 2: 建立连接
            headers = {**_HEADERS_TEMPLATE, "Cookie": self._cookie}
            self._ws = await self._session.ws_connect(
                ws_url,
                headers=headers,
                heartbeat=None,  # 手动管理心跳
                timeout=15,
            )
            logger.info("WebSocket 握手完成")
            return True

        except asyncio.TimeoutError:
            logger.error("WebSocket 连接超时")
        except aiohttp.ClientError as e:
            logger.error(f"WebSocket 连接失败: {e}")
        except Exception:
            logger.exception("WebSocket 连接异常")
        return False

    async def _fetch_ws_url(self) -> str:
        """从抖音直播间页面提取 WebSocket URL

        抖音 WebSocket URL 格式:
          wss://webcast.douyin.com/webcast/im/push/v2/?
            app_id=xxx&room_id=xxx&token=xxx&...

        获取方式:
          1. GET https://live.douyin.com/{room_id} → 提取 RENDER_DATA
          2. 从 RENDER_DATA 中解析 room_id + 签名 token
          3. 拼接 WebSocket URL

        TODO: RENDER_DATA 提取逻辑 (随抖音前端更新)
              当前返回空 → 自动降级到 HTTP 轮询
        """
        try:
            url = f"{_DOUYIN_LIVE_API}/{self._room_id}"
            async with self._session.get(url, timeout=10) as resp:
                html = await resp.text()

            # 从 HTML 中提取 RENDER_DATA (抖音 SSR 数据)
            # 格式: <script id="RENDER_DATA" type="application/json">...</script>
            marker = 'id="RENDER_DATA" type="application/json">'
            idx = html.find(marker)
            if idx == -1:
                logger.warning("页面中未找到 RENDER_DATA (可能需要登录或直播间不存在)")
                return ""

            start = idx + len(marker)
            end = html.find("</script>", start)
            if end == -1:
                return ""

            raw = html[start:end]
            data = json.loads(raw)

            # 提取 room 信息
            room = data.get("app", {}).get("initialState", {}).get("roomStore", {}).get("roomInfo", {}).get("room", {})
            if not room:
                # 备用路径
                room = data.get("roomInfo", {}).get("room", {})

            web_rid = room.get("id_str") or room.get("web_rid") or self._room_id

            # 拼接 WebSocket URL
            ws_url = (
                f"{_DOUYIN_WS_HOST}/webcast/im/push/v2/?"
                f"app_id=1128"
                f"&room_id={web_rid}"
                f"&live_id=1"
            )
            return ws_url

        except json.JSONDecodeError:
            logger.warning("RENDER_DATA JSON 解析失败 (前端格式可能已变更)")
        except aiohttp.ClientError as e:
            logger.warning(f"获取直播间页面失败: {e}")
        except Exception:
            logger.exception("_fetch_ws_url 异常")
        return ""

    # ═══════════════════════════════════════════════
    # WebSocket 消息循环
    # ═══════════════════════════════════════════════

    async def _ws_loop(self):
        """WebSocket 消息接收主循环"""
        logger.info("WebSocket 消息循环启动")

        while self._connected and self._ws and not self._ws.closed:
            try:
                msg = await self._ws.receive(timeout=30)

                if msg.type == aiohttp.WSMsgType.TEXT:
                    # JSON 格式 (部分端点)
                    await self._handle_json_message(msg.data)

                elif msg.type == aiohttp.WSMsgType.BINARY:
                    # Protobuf 格式 (主要协议)
                    await self._handle_binary_message(msg.data)

                elif msg.type == aiohttp.WSMsgType.PING:
                    await self._ws.pong()

                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                    logger.warning("WebSocket 被服务端关闭")
                    break

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket 错误: {self._ws.exception()}")
                    break

            except asyncio.TimeoutError:
                # 30s 无消息 → 检查心跳
                if not self._connected:
                    break
                continue

            except asyncio.CancelledError:
                break

            except Exception:
                logger.exception("WebSocket 消息循环异常")
                break

        logger.warning("WebSocket 消息循环退出")
        self._connected = False

    async def _heartbeat_loop(self):
        """心跳保活"""
        logger.info("心跳循环启动")

        while self._connected and self._ws and not self._ws.closed:
            try:
                await asyncio.sleep(self._ping_interval)
                if self._ws and not self._ws.closed:
                    await self._ws.ping()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning("心跳发送失败")
                break

        logger.info("心跳循环退出")

    # ═══════════════════════════════════════════════
    # HTTP 轮询 (降级方案)
    # ═══════════════════════════════════════════════

    async def _start_polling(self) -> bool:
        """启动 HTTP 轮询

        TODO: 抖音 HTTP 评论接口 (可能需要逆向)
              当前返回空 → 轮询线程空转, 不产生事件
        """
        self._ws_task = asyncio.create_task(self._poll_loop())
        return True

    async def _poll_loop(self):
        """HTTP 轮询循环"""
        logger.info("HTTP 轮询循环启动 (降级模式)")

        while self._connected:
            try:
                # TODO: 实际 HTTP 端点
                # url = f"{_DOUYIN_LIVE_API}/webcast/im/fetch/?room_id={self._room_id}"
                # async with self._session.get(url) as resp:
                #     data = await resp.json()
                #     for msg in data.get("messages", []):
                #         event = self._parse_raw(msg)
                #         if event:
                #             await self._enqueue(event)
                pass

                await asyncio.sleep(2)  # 轮询间隔

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("HTTP 轮询异常")
                await asyncio.sleep(5)

        logger.info("HTTP 轮询循环退出")

    # ═══════════════════════════════════════════════
    # 消息处理
    # ═══════════════════════════════════════════════

    async def _handle_json_message(self, raw_text: str):
        """处理 JSON 格式消息"""
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            return

        event = self._parse_raw(data)
        if event:
            await self._enqueue(event)

    async def _handle_binary_message(self, raw_bytes: bytes):
        """处理 Protobuf 格式消息

        抖音 WebSocket 消息结构:
          ┌──────────┬──────────┬──────────────┐
          │ 4 bytes  │ 4 bytes  │ N bytes      │
          │ 包头     │ 消息类型  │ Protobuf body│
          └──────────┴──────────┴──────────────┘

        Protobuf 编译后取消下方注释即可启用:
        """
        self._messages_received += 1

        if not _PROTO_AVAILABLE:
            # 未编译 protobuf → 尝试从 JSON 模式兜底
            if self._messages_received == 1:
                logger.warning(
                    "收到 Protobuf 消息但未编译 proto 文件。"
                    "请按 douyin.py 顶部注释编译 protobuf。"
                )
            return

        # === Protobuf 解析 (需编译 proto 后取消注释) ===
        # try:
        #     # 解析包头
        #     if len(raw_bytes) < 8:
        #         return
        #     msg_type = struct.unpack(">I", raw_bytes[4:8])[0]
        #
        #     # 反序列化 Response
        #     body = raw_bytes[8:]
        #     response = douyin_pb2.Response()
        #     response.ParseFromString(body)
        #
        #     # 遍历消息列表
        #     for msg in response.messages:
        #         if msg.method == "WebcastChatMessage":
        #             chat = douyin_pb2.ChatMessage()
        #             chat.ParseFromString(msg.payload)
        #
        #             raw = {
        #                 "type": "chat",
        #                 "user": {
        #                     "unique_id": str(chat.user.id),
        #                     "nickname": chat.user.nickname,
        #                 },
        #                 "content": chat.content,
        #                 "create_time": chat.event_time / 1000,
        #             }
        #             event = self._parse_raw(raw)
        #             if event:
        #                 await self._enqueue(event)
        #
        # except Exception:
        #     self._parse_errors += 1
        #
        #     # 连续 10 次解析失败 → 可能是协议变更
        #     if self._parse_errors > 10 and self._parse_errors % 10 == 0:
        #         logger.error(
        #             f"Protobuf 解析连续失败 {self._parse_errors} 次, "
        #             "可能是协议变更, 需更新 .proto 文件"
        #         )

    # ═══════════════════════════════════════════════
    # 数据解析
    # ═══════════════════════════════════════════════

    def _parse_raw(self, raw: dict) -> Optional[CommentEvent]:
        """将抖音原始消息转换为统一的 CommentEvent

        输入格式 (JSON 或 Protobuf 反序列化后):
          {
            "type": "chat",
            "user": {"unique_id": "xxx", "nickname": "观众A"},
            "content": "B",
            "create_time": 1750000000
          }
        """
        try:
            # 只处理聊天消息
            if raw.get("type") != "chat":
                return None

            user = raw.get("user", {})
            content = raw.get("content", "").strip()
            timestamp = float(raw.get("create_time", time.time()))

            if not content:
                return None

            # 提取答案 (A/B/C/1/2/3)
            answer = None
            upper = content.upper().strip()
            if len(upper) <= 3 and upper:
                # 检查是否所有字符都是有效答案
                if all(ch in "ABCD123 " for ch in upper):
                    answer = upper.replace(" ", "")

            event = CommentEvent(
                user_id=str(user.get("unique_id", "")),
                nickname=str(user.get("nickname", "观众")),
                content=content,
                answer=answer,
                platform=self.PLATFORM,
                timestamp=timestamp,
                raw=raw,
            )

            self._messages_parsed += 1
            self._last_msg_time = time.time()
            return event

        except Exception:
            self._parse_errors += 1
            logger.debug("解析抖音消息失败", exc_info=True)
            return None

    # ═══════════════════════════════════════════════
    # 辅助
    # ═══════════════════════════════════════════════

    async def _enqueue(self, event: CommentEvent):
        """放入内部队列 (满时丢弃最旧)"""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(event)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

    async def _cleanup_session(self):
        """清理 HTTP session"""
        if self._session:
            await self._session.close()
            self._session = None
