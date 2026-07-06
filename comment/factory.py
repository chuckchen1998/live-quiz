"""评论源工厂 — 根据配置创建对应实现"""

from .base import CommentSource
from .douyin import DouyinCommentSource
from .replay import ReplayCommentSource
from .simulator import SimulatorSource


class CommentSourceFactory:
    """根据 source_type 创建评论源 — main.py 唯一调用入口

    用法:
        source = CommentSourceFactory.create("simulator", interval=0.3)
        source = CommentSourceFactory.create("douyin", room_id="xxx", cookie="xxx")
        source = CommentSourceFactory.create("replay", file_path="data/replay_comments.json", speed=5.0)
    """

    _registry: dict[str, type] = {
        "simulator": SimulatorSource,
        "douyin": DouyinCommentSource,
        "replay": ReplayCommentSource,
    }

    @classmethod
    def register(cls, source_type: str, source_cls: type):
        """注册新的评论源类型（第三方扩展用）"""
        if not issubclass(source_cls, CommentSource):
            raise TypeError(f"{source_cls} 必须实现 CommentSource 接口")
        cls._registry[source_type] = source_cls

    @classmethod
    def create(cls, source_type: str, **kwargs) -> CommentSource:
        """创建评论源实例

        Args:
            source_type: "simulator" | "douyin" | ...
            **kwargs: 传递给具体实现的构造参数

        Returns:
            CommentSource 实例

        Raises:
            ValueError: 未知的 source_type
        """
        source_cls = cls._registry.get(source_type)
        if source_cls is None:
            raise ValueError(
                f"未知评论源类型: {source_type!r}。"
                f"可用: {list(cls._registry.keys())}"
            )
        return source_cls(**kwargs)

    @classmethod
    def available(cls) -> list[str]:
        """列出所有已注册的评论源类型"""
        return list(cls._registry.keys())
