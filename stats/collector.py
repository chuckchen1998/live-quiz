"""实时统计模块 — 汇总每位用户的答题结果（含去重）"""

from dataclasses import dataclass, field
from typing import Optional


def _normalize_key(raw: str) -> str:
    """将用户答案归一化为选项字母 A/B/C/D

    支持: "A", "A.", "1", "a", "B. 列表" 等格式
    """
    s = raw.strip().upper()
    if not s:
        return ""
    ch = s[0]
    if ch in "ABCD":
        return ch
    if ch.isdigit() and 1 <= int(ch) <= 9:
        return chr(ord("A") + int(ch) - 1)
    return ""


@dataclass
class QuestionStats:
    """单题统计"""
    question_id: int
    question_text: str = ""
    options: list[str] = field(default_factory=list)
    correct_answer: str = ""
    votes: dict[str, int] = field(default_factory=dict)
    total_votes: int = 0
    correct_count: int = 0
    phase: str = "idle"


class StatsCollector:
    """实时统计收集器 — 每位用户每题限投 1 票"""

    def __init__(self):
        self.current: Optional[QuestionStats] = None
        self.history: list[QuestionStats] = []
        # 去重：{user_id: {question_id: True}}
        self._voters: dict[str, dict[int, bool]] = {}

    def new_question(self, question_id: int, question_text: str,
                     options: list[str], correct: str):
        """开始新题，重置统计"""
        if self.current:
            self.history.append(self.current)

        option_keys = [_normalize_key(o) for o in options]

        self.current = QuestionStats(
            question_id=question_id,
            question_text=question_text,
            options=option_keys,
            correct_answer=_normalize_key(correct),
            votes={k: 0 for k in option_keys},
            phase="answering",
        )

    def record_vote(self, user_id: str, user_answer: str) -> bool:
        """记录一票。返回 True=有效投票，False=重复/无效"""
        if not self.current:
            return False

        # 去重检查
        qid = self.current.question_id
        if user_id in self._voters and qid in self._voters[user_id]:
            return False

        key = _normalize_key(user_answer)
        if not key or key not in self.current.votes:
            return False

        self.current.votes[key] += 1
        self.current.total_votes += 1

        if user_id not in self._voters:
            self._voters[user_id] = {}
        self._voters[user_id][qid] = True

        return True

    def mark_correct(self, user_id: str, user_answer: str):
        """标记一条正确答案"""
        if not self.current:
            return
        key = _normalize_key(user_answer)
        if key == self.current.correct_answer:
            self.current.correct_count += 1

    def set_phase(self, phase: str):
        if self.current:
            self.current.phase = phase

    def to_dict(self) -> dict:
        """导出为字典（供 JSON 序列化推送给前端）"""
        if not self.current:
            return {"phase": "idle", "votes": {}, "total": 0, "history": []}
        return {
            "phase": self.current.phase,
            "question_id": self.current.question_id,
            "question_text": self.current.question_text,
            "options": self.current.options,
            "correct_answer": self.current.correct_answer,
            "votes": self.current.votes,
            "total": self.current.total_votes,
            "correct_count": self.current.correct_count,
            "history_count": len(self.history),
        }
