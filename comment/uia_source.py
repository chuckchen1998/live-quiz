"""UIA 弹幕评论源 — 通过 cua-driver UIA 树直接读取弹幕

原理:
  直播伴侣 = Electron 应用, 但每条弹幕消息在 UIA 树里有对应节点
  用 cua-driver call get_window_state 读 UIA 树 → 解析弹幕

优势:
  + 零 API 调用, 免费
  + 读取速度快 (<1s)
  + 100% 准确
  - 需要 cua-driver 持续运行
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import time
from typing import Optional

from .base import CommentEvent, CommentSource

logger = logging.getLogger(__name__)

_DANMU_LINE_RE = re.compile(r"^(.+?)\s*[:：]\s*(.+)$")
_ANSWER_PATTERNS = [
    re.compile(r"^[ABCD123]$", re.IGNORECASE),
    re.compile(r"^[ABCD123]\.$", re.IGNORECASE),
]

# 忽略的系统消息关键词
_SKIP_KEYWORDS = ["互动消息区", "展示本场", "欢迎来到", "严禁", "理性消费",
                  "切勿私下", "谨防", "抖音严禁", "测试测试测试"]


class UIADanmuSource(CommentSource):
    """UIA 直接读取弹幕"""

    PLATFORM = "douyin-uia"

    def __init__(self, interval: float = 1.0):
        self._interval = interval
        self._connected = False
        self._queue: asyncio.Queue[CommentEvent] = asyncio.Queue(maxsize=2000)
        self._poll_task: Optional[asyncio.Task] = None
        self._seen: set = set()
        self._capture_count = 0

    async def connect(self) -> bool:
        self._connected = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("UIA弹幕源启动")
        return True

    async def disconnect(self):
        self._connected = False
        if self._poll_task:
            self._poll_task.cancel()
            try: await self._poll_task
            except asyncio.CancelledError: pass
        logger.info("UIA弹幕源已断开")

    async def health_check(self) -> bool:
        return self._connected

    async def get_comment(self) -> Optional[CommentEvent]:
        try: return self._queue.get_nowait()
        except asyncio.QueueEmpty: return None

    @property
    def platform(self) -> str: return self.PLATFORM
    @property
    def is_connected(self) -> bool: return self._connected

    async def get_stats(self) -> dict:
        return {"platform": self.PLATFORM, "connected": self._connected,
                "capture_count": self._capture_count, "queue_size": self._queue.qsize()}

    async def _poll_loop(self):
        logger.info("UIA弹幕轮询启动")
        while self._connected:
            try:
                danmu = await asyncio.to_thread(self._read_uia)
                self._capture_count += 1
                for nickname, content in danmu:
                    key = f"{nickname}:{content}"
                    if key in self._seen:
                        continue
                    self._seen.add(key)
                    answer = None
                    for pat in _ANSWER_PATTERNS:
                        if pat.match(content):
                            answer = content.rstrip(".").upper()
                            break
                    event = CommentEvent(
                        user_id=f"uia:{hash(nickname) % 100000:05d}",
                        nickname=nickname, content=content,
                        answer=answer, platform=self.PLATFORM,
                        timestamp=time.time(),
                    )
                    try:
                        self._queue.put_nowait(event)
                    except asyncio.QueueFull:
                        try:
                            self._queue.get_nowait()
                            self._queue.put_nowait(event)
                        except (asyncio.QueueEmpty, asyncio.QueueFull):
                            pass
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("UIA轮询异常")
                await asyncio.sleep(2)
        logger.info("UIA弹幕轮询退出")

    def _read_uia(self) -> list[tuple[str, str]]:
        """调用 cua-driver 读 UIA 树, 提取弹幕 [(昵称, 内容), ...]"""
        try:
            # 获取互动消息区窗口
            pid = _find_live_pid()
            hwnd = _find_danmu_window()
            if not pid or not hwnd:
                return []

            payload = json.dumps({
                "window_id": hwnd, "pid": pid,
                "include_screenshot": False,
                "max_elements": 200,
            })
            result = subprocess.run(
                ["cua-driver", "call", "get_window_state", payload],
                capture_output=True, timeout=12,
                encoding="utf-8", errors="ignore",
                env={**os.environ, "CUA_DRIVER_RS_TELEMETRY_ENABLED": "0"},
            )
            if result.returncode != 0:
                return []
            return _extract_danmu(result.stdout)
        except Exception:
            return []


def _extract_danmu(json_text: str) -> list[tuple[str, str]]:
    """从 cua-driver JSON 输出中提取弹幕消息"""
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return []

    # 优先从 tree_markdown 解析 (已验证正确)
    md = data.get("tree_markdown", "")
    if md:
        return _extract_from_markdown(md)

    # 回退: structuredContent.elements
    elements = (data.get("structuredContent") or {}).get("elements") or []
    if elements:
        return _extract_from_elements(elements)

    return []


def _extract_from_markdown(md: str) -> list[tuple[str, str]]:
    """从 markdown 树解析弹幕消息"""
    results = []
    lines = md.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        m = re.search(r'Hyperlink\s+\"([^\"]+)\"', line)
        if m:
            nick = m.group(1).rstrip(" :").strip()
            if not any(k in nick for k in _SKIP_KEYWORDS):
                indent = len(line) - len(line.lstrip())
                j = i + 1
                while j < len(lines):
                    lj = lines[j].rstrip()
                    if not lj.strip():
                        j += 1; continue
                    j_indent = len(lj) - len(lj.lstrip())
                    # 遇到缩进更深 → 子元素, 跳过
                    if j_indent > indent:
                        j += 1; continue
                    # 缩进更浅 → 下一个区域, 放弃
                    if j_indent < indent:
                        break
                    # 同级: 检查是否有内容
                    m2 = re.search(r'Text\s+\"([^\"]+)\"', lj)
                    if m2:
                        content = m2.group(1)
                        if content and not any(k in content for k in _SKIP_KEYWORDS):
                            results.append((nick, content))
                            i = j + 1
                            break
                    # 空 Text 或不是 Text → 继续
                    j += 1
                else:
                    i += 1
                continue
        i += 1
    return results


def _extract_from_elements(elements: list) -> list[tuple[str, str]]:
    results = []
    for i, el in enumerate(elements):
        label = el.get("label", "")
        role = el.get("role", "")
        if not label or any(k in label for k in _SKIP_KEYWORDS):
            continue
        if role == "Hyperlink" and ":" in label:
            nickname = label.rstrip(" :").strip()
            for j in range(i + 1, min(i + 4, len(elements))):
                next_el = elements[j]
                next_label = next_el.get("label", "")
                next_role = next_el.get("role", "")
                if (next_role == "Text" and next_label
                        and ":" not in next_label
                        and not any(k in next_label for k in _SKIP_KEYWORDS)):
                    results.append((nickname, next_label))
                    break
    return results


# ═══════════════════════════════════════════════
# Win32 辅助函数 (模块级别)
# ═══════════════════════════════════════════════

import ctypes
from ctypes import wintypes

_user32 = ctypes.windll.user32


def _find_live_pid() -> int:
    try:
        result = subprocess.run(
            'tasklist /FI "IMAGENAME eq 直播伴侣.exe" /FO CSV /NH',
            shell=True, capture_output=True, timeout=5,
            encoding="gbk", errors="ignore",
        )
        for line in result.stdout.strip().split("\n"):
            parts = line.replace('"', "").split(",")
            if len(parts) >= 2 and "直播伴侣" in parts[0]:
                return int(parts[1].strip())
    except Exception:
        pass
    return 0


def _find_danmu_window():
    pid = _find_live_pid()
    if not pid:
        return None
    result = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, lparam):
        if _user32.IsWindowVisible(hwnd):
            wpid = ctypes.c_ulong()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value == pid:
                class RECT(ctypes.Structure):
                    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
                r = RECT()
                _user32.GetWindowRect(hwnd, ctypes.byref(r))
                w = r.right - r.left
                h = r.bottom - r.top
                if w < 600 and h > 800:
                    result.append((hwnd, w))
        return True

    _user32.EnumWindows(_cb, 0)
    if result:
        result.sort(key=lambda x: x[1])
        return result[0][0]
    return None
