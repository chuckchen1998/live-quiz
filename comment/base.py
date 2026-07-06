"""统一评论数据源抽象接口 — 业务层只消费 CommentEvent"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CommentEvent:
    """所有评论源输出的统一事件 — 业务层唯一消费的数据结构

    无论评论来自模拟器、抖音、快手还是任何平台，
    都先转换为 CommentEvent，再送入 quiz/stats/display。
    """

    # ── 用户标识 ──
    user_id: str                # 平台唯一 ID（模拟 UUID / 抖音 open_id）
    nickname: str               # 显示昵称

    # ── 评论内容 ──
    content: str                # 原始评论文本
    answer: Optional[str] = None  # 解析后的答案 A/B/C/1/2/3，无则为 None

    # ── 元信息 ──
    platform: str = "unknown"   # "simulator" | "douyin" | "kuaishou" | ...
    timestamp: float = 0.0      # Unix 时间戳（秒）
    raw: Optional[dict] = None  # 原始平台数据（调试/扩展用，业务层忽略）


class CommentSource(ABC):
    """评论源抽象接口 — 所有平台实现此接口

    生命周期:
      1. connect()      — 建立连接
      2. get_comment()  — 循环获取（非阻塞）
      3. disconnect()   — 断开连接

    业务层（quiz/stats/display）不依赖任何具体实现，
    只消费 CommentSource 接口。
    """

    # ── 生命周期 ──

    @abstractmethod
    async def connect(self) -> bool:
        """建立连接。返回 True=成功，False=失败"""
        ...

    @abstractmethod
    async def disconnect(self):
        """断开连接，释放所有资源"""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查。返回 True=连接正常"""
        ...

    # ── 数据获取 ──

    @abstractmethod
    async def get_comment(self) -> Optional[CommentEvent]:
        """获取一条评论。无数据返回 None（非阻塞，立即返回）"""
        ...

    # ── 元信息 ──

    @property
    @abstractmethod
    def platform(self) -> str:
        """平台标识: "simulator" | "douyin" | "kuaishou" """
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """当前连接状态"""
        ...

    # ── 统计（可选覆写） ──

    async def get_stats(self) -> dict:
        """连接统计: {messages_received, errors, uptime, ...}"""
        return {}
