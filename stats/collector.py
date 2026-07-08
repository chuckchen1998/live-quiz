"""实时统计模块 — 汇总每位用户的答题结果（含去重 + 排行榜 + 积分）"""

from dataclasses import dataclass, field
from typing import Optional


def _normalize_key(raw: str) -> str:
    s = raw.strip().upper()
    if not s: return ""
    ch = s[0]
    if ch in "ABCD": return ch
    if ch.isdigit() and 1 <= int(ch) <= 9: return chr(ord("A") + int(ch) - 1)
    return ""


@dataclass
class QuestionStats:
    question_id: int
    question_text: str = ""
    option_texts: list[str] = field(default_factory=list)  # 原始选项（含内容）
    options: list[str] = field(default_factory=list)        # 标准化后的字母
    correct_answer: str = ""
    points: int = 1
    votes: dict[str, int] = field(default_factory=dict)
    total_votes: int = 0
    correct_count: int = 0
    phase: str = "idle"


class StatsCollector:
    def __init__(self):
        self.current: Optional[QuestionStats] = None
        self.history: list[QuestionStats] = []
        self._voters: dict[str, dict[int, str]] = {}  # user_id -> {qid: last_answer_key}
        self._user_stats: dict[str, dict] = {}

    def new_question(self, question_id: int, question_text: str,
                     options: list[str], correct: str, points: int = 1):
        if self.current: self.history.append(self.current)
        option_keys = [_normalize_key(o) for o in options]
        self.current = QuestionStats(
            question_id=question_id, question_text=question_text,
            option_texts=list(options), options=option_keys,
            correct_answer=_normalize_key(correct),
            points=points, votes={k: 0 for k in option_keys}, phase="answering")

    def record_vote(self, user_id: str, user_answer: str) -> bool:
        if not self.current: return False
        qid = self.current.question_id
        key = _normalize_key(user_answer)
        if not key or key not in self.current.votes: return False

        # 如果该用户之前在这道题投过票，先撤销旧票
        if user_id in self._voters and qid in self._voters[user_id]:
            old_key = self._voters[user_id][qid]
            if old_key in self.current.votes and self.current.votes[old_key] > 0:
                self.current.votes[old_key] -= 1
                self.current.total_votes -= 1

        self.current.votes[key] += 1
        self.current.total_votes += 1
        if user_id not in self._voters:
            self._voters[user_id] = {}
        self._voters[user_id][qid] = key
        return True

    def mark_correct(self, user_id: str, user_answer: str, nickname: str = "", points: int = 1):
        if not self.current: return
        if user_id not in self._user_stats:
            self._user_stats[user_id] = {"nickname": nickname or user_id, "correct": 0, "total": 0, "points": 0}
        self._user_stats[user_id]["total"] += 1
        key = _normalize_key(user_answer)
        if key == self.current.correct_answer:
            self.current.correct_count += 1
            self._user_stats[user_id]["correct"] += 1
            self._user_stats[user_id]["points"] += points

    def set_phase(self, phase: str):
        if self.current: self.current.phase = phase

    def leaderboard(self, top_n: int = 10, sort_by: str = "points") -> list[dict]:
        users = list(self._user_stats.values())
        if sort_by == "points":
            users.sort(key=lambda u: (-u["points"], -u["correct"], u["total"]))
        else:
            users.sort(key=lambda u: (-u["correct"], -u["points"], u["total"]))
        result = []
        for rank, user in enumerate(users[:top_n], 1):
            result.append({
                "rank": rank, "nickname": user["nickname"], "correct": user["correct"],
                "total": user["total"], "points": user["points"],
                "accuracy": round(user["correct"] / max(user["total"], 1) * 100, 1)})
        return result

    def user_detail(self, user_id: str) -> dict:
        """返回单个用户的详细统计"""
        if user_id not in self._user_stats:
            return {}
        u = self._user_stats[user_id]
        return {
            "user_id": user_id, "nickname": u["nickname"],
            "correct": u["correct"], "total": u["total"], "points": u["points"],
            "accuracy": round(u["correct"] / max(u["total"], 1) * 100, 1),
            "rank": self._user_rank(user_id),
        }

    def _user_rank(self, user_id: str) -> int:
        if user_id not in self._user_stats:
            return -1
        target = self._user_stats[user_id]
        users = list(self._user_stats.values())
        users.sort(key=lambda u: (-u["points"], -u["correct"], u["total"]))
        for i, u in enumerate(users, 1):
            if u is target: return i
        return -1

    def to_dict(self) -> dict:
        if not self.current:
            return {"phase": "idle", "votes": {}, "total": 0, "history": [], "leaderboard": self.leaderboard()}
        return {
            "phase": self.current.phase, "question_id": self.current.question_id,
            "question_text": self.current.question_text, "options": self.current.option_texts,
            "correct_answer": self.current.correct_answer, "points": self.current.points,
            "votes": self.current.votes, "total": self.current.total_votes,
            "correct_count": self.current.correct_count, "history_count": len(self.history),
            "leaderboard": self.leaderboard()}
