"""答题引擎 — 出题、判题、调度"""

import json
import random
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable

import config
from .timer import CountdownTimer


@dataclass
class Question:
    """一道题"""
    id: int
    question: str
    options: list[str]
    answer: str  # "A" / "B" / "C" / "1" / "2" / "3"


@dataclass
class QuizState:
    """当前答题状态 — 推送给展示模块"""
    question: Optional[Question] = None
    time_left: int = 0
    phase: str = "idle"         # idle | answering | result | between
    total_questions: int = 0
    current_index: int = 0      # 当前第几题(1-based)
    message: str = ""


class QuizEngine:
    """答题核心引擎"""

    def __init__(self):
        self.questions: list[Question] = []
        self._timer: Optional[CountdownTimer] = None
        self._current_index = 0
        self._current_phase = "idle"  # 当前阶段
        self._on_state: Optional[Callable[[QuizState], Awaitable[None]]] = None

    def load_questions(self, path: str = "data/questions.json"):
        """从 JSON 加载题库"""
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        self.questions = [Question(**q) for q in raw]
        random.shuffle(self.questions)

    def on_state_change(self, handler: Callable[[QuizState], Awaitable[None]]):
        """注册状态变化回调"""
        self._on_state = handler

    async def _emit(self, **kwargs):
        if self._on_state:
            await self._on_state(QuizState(
                question=self.questions[self._current_index - 1] if 0 < self._current_index <= len(self.questions) else None,
                total_questions=len(self.questions),
                current_index=self._current_index,
                **kwargs,
            ))

    async def run(self):
        """运行完整答题流程"""
        if not self.questions:
            await self._emit(phase="idle", message="题库为空")
            return

        for i, q in enumerate(self.questions):
            self._current_index = i + 1

            # ① 出题
            self._current_phase = "answering"
            await self._emit(phase="answering", time_left=config.QUESTION_TIME)
            await self._run_timer(config.QUESTION_TIME)

            # ② 公布答案
            self._current_phase = "result"
            await self._emit(phase="result", time_left=0, message=f"正确答案: {q.answer}")

            # ③ 题间休息
            if i < len(self.questions) - 1:
                self._current_phase = "between"
                await self._emit(phase="between", time_left=config.BETWEEN_QUESTIONS, message=f"下一题即将开始...")
                await self._run_timer(config.BETWEEN_QUESTIONS)

        self._current_phase = "idle"
        await self._emit(phase="idle", message="答题结束！")

    async def _run_timer(self, seconds: int):
        self._timer = CountdownTimer(seconds, on_tick=self._on_tick)
        await self._timer.start()

    async def _on_tick(self, remaining: int):
        """每秒回调"""
        if self._on_state:
            q = self.questions[self._current_index - 1] if 0 < self._current_index <= len(self.questions) else None
            await self._on_state(QuizState(
                question=q,
                time_left=remaining,
                phase=self._current_phase,
                total_questions=len(self.questions),
                current_index=self._current_index,
            ))

    def check_answer(self, user_answer: str) -> bool:
        """判断用户答案是否正确"""
        if self._current_index < 1 or self._current_index > len(self.questions):
            return False
        q = self.questions[self._current_index - 1]
        # 规范化：提取首字母/数字
        raw = user_answer.strip().upper()
        # 尝试匹配 "A." "A" "1" 等格式
        ans = raw[0] if raw and raw[0] in "ABCD123" else ""
        if not ans:
            return False
        expected = q.answer.strip().upper()
        # 直接匹配 或 数字↔字母互转 (1↔A, 2↔B, 3↔C)
        if ans.isdigit():
            ans = chr(ord("A") + int(ans) - 1)
        if expected.isdigit():
            expected = chr(ord("A") + int(expected) - 1)
        return ans == expected
