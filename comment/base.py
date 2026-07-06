"""评论数据源抽象接口"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class Comment:
    """一条评论"""
    user: str       # 用户名
    text: str       # 评论内容
    answer: Optional[str] = None  # 解析出的答案（A/B/C 或 1/2/3）


class CommentSource(ABC):
    """评论源抽象类 — 后期替换真实数据源时实现此接口"""

    @abstractmethod
    async def start(self):
        """启动数据源"""
        ...

    @abstractmethod
    async def stop(self):
        """停止数据源"""
        ...

    @abstractmethod
    async def get_comment(self) -> Optional[Comment]:
        """获取一条评论，无数据返回 None"""
        ...
