"""统一评论数据源抽象接口 — 业务层只消费 CommentEvent"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

_ANSWER_CHARS = set("ABCD123")
_ANSWER_PREFIXES = ["选", "看", "答", "投", "压", "肯定是", "绝对是", "应该是",
                    "答案是", "答案", "我选", "我投", "我压", "我猜", "我觉",
                    "果断", "直接", "必须", "当然", "肯定"]

def _extract_answer(content: str) -> Optional[str]:
    if not content: return None
    s = content.strip()
    if len(s) == 1 and s.upper() in _ANSWER_CHARS: return s.upper()
    if len(s) == 2 and s[-1] == "." and s[0].upper() in _ANSWER_CHARS: return s[0].upper()
    cleaned = s.replace(" ", "")
    if len(cleaned) == 1 and cleaned.upper() in _ANSWER_CHARS: return cleaned.upper()
    for prefix in _ANSWER_PREFIXES:
        if s.startswith(prefix):
            after = s[len(prefix):].strip().upper()
            if after and after[0] in _ANSWER_CHARS: return after[0]
    return None

@dataclass
class CommentEvent:
    user_id: str
    nickname: str
    content: str
    answer: Optional[str] = None
    platform: str = "unknown"
    timestamp: float = 0.0
    raw: Optional[dict] = None
    def __post_init__(self):
        if self.answer is None and self.content: self.answer = _extract_answer(self.content)

class CommentSource(ABC):
    @abstractmethod
    async def connect(self) -> bool: ...
    @abstractmethod
    async def disconnect(self): ...
    @abstractmethod
    async def health_check(self) -> bool: ...
    @abstractmethod
    async def get_comment(self) -> Optional[CommentEvent]: ...
    @property
    @abstractmethod
    def platform(self) -> str: ...
    @property
    @abstractmethod
    def is_connected(self) -> bool: ...
    async def get_stats(self) -> dict: return {}
