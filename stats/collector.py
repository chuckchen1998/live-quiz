"""实时统计模块 — 汇总每位用户的答题结果"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class QuestionStats:
    """单题统计"""
    question_id: int
    question_text: str = ""
    options: list[str] = field(default_factory=list)
    correct_answer: str = ""
    votes: dict[str, int] = field(default_factory=dict)      # {"A": 5, "B": 3}
    total_votes: int = 0
    correct_count: int = 0
    phase: str = "idle"       # idle | answering | result


class StatsCollector:
    """实时统计收集器"""

    def __init__(self):
        self.current: Optional[QuestionStats] = None
        self.history: list[QuestionStats] = []

    def new_question(self, question_id: int, question_text: str, options: list[str], correct: str):
        """开始新题，重置统计"""
        if self.current:
            self.history.append(self.current)
        # 解析选项字母: "A. xxx" → "A"
        option_keys = []
        for o in options:
            key = o.strip()[0] if o.strip() else "?"
            option_keys.append(key)

        self.current = QuestionStats(
            question_id=question_id,
            question_text=question_text,
            options=option_keys,
            correct_answer=correct.strip().upper(),
            votes={k: 0 for k in option_keys},
            phase="answering",
        )

    def record_vote(self, user_answer: str):
        """记录一票"""
        if not self.current:
            return
        ans = user_answer.strip().upper()
        # 规范化: "A." → "A", "1" → "A"
        if ans and ans[0] in "ABCD123":
            key = ans[0]
            if key.isdigit():
                key = chr(ord("A") + int(key) - 1)
            if key in self.current.votes:
                self.current.votes[key] += 1
                self.current.total_votes += 1

    def mark_correct(self, user_answer: str):
        """标记一条正确答案"""
        if not self.current:
            return
        ans = user_answer.strip().upper()
        if ans and ans[0] in "ABCD123":
            key = ans[0]
            if key.isdigit():
                key = chr(ord("A") + int(key) - 1)
            if key == self.current.correct_answer:
                self.current.correct_count += 1

    def set_phase(self, phase: str):
        if self.current:
            self.current.phase = phase

    def to_dict(self) -> dict:
        """导出为字典（供JSON序列化推送给前端）"""
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
