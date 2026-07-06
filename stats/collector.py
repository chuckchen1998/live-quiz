"""实时统计模块 — 汇总每位用户的答题结果"""

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
    """实时统计收集器"""

    def __init__(self):
        self.current: Optional[QuestionStats] = None
        self.history: list[QuestionStats] = []

    def new_question(self, question_id: int, question_text: str,
                     options: list[str], correct: str):
        """开始新题，重置统计
        
        options 支持 "A. xxx" 或 "1" 两种格式，统一归一化为 A/B/C
        """
        if self.current:
            self.history.append(self.current)

        # 统一将选项归一化为字母键
        option_keys = [_normalize_key(o) for o in options]

        self.current = QuestionStats(
            question_id=question_id,
            question_text=question_text,
            options=option_keys,
            correct_answer=_normalize_key(correct),
            votes={k: 0 for k in option_keys},
            phase="answering",
        )

    def record_vote(self, user_answer: str):
        """记录一票"""
        self._apply_vote(user_answer, mark_correct=False)

    def mark_correct(self, user_answer: str):
        """标记一条正确答案"""
        self._apply_vote(user_answer, mark_correct=True)

    def _apply_vote(self, user_answer: str, *, mark_correct: bool):
        """统一投票/标记处理"""
        if not self.current:
            return
        key = _normalize_key(user_answer)
        if not key or key not in self.current.votes:
            return

        if not mark_correct:
            self.current.votes[key] += 1
            self.current.total_votes += 1
        elif key == self.current.correct_answer:
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
