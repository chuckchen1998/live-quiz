"""答题引擎 — 出题、判题、调度、Admin 控制"""

import asyncio, json, logging, random
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable
import config
from .timer import CountdownTimer
logger = logging.getLogger(__name__)

@dataclass
class Question:
    id: int; question: str; options: list[str]; answer: str; points: int = 1
    explanation: str = ""  # 题目解析
    category: str = ""     # 分类标签（如"夏朝""商朝"等）

@dataclass
class QuizState:
    question: Optional[Question] = None; time_left: int = 0; phase: str = "idle"
    total_questions: int = 0; current_index: int = 0; message: str = ""
    explanation: str = ""; category: str = ""

class QuizEngine:
    def __init__(self):
        self.questions: list[Question] = []; self._timer = None; self._current_index = 0
        self._current_phase = "idle"; self._on_state = None
        self._pause_event = asyncio.Event(); self._pause_event.set()
        self._skip_current = False; self._reveal_now = False; self._next_event = asyncio.Event()

    @property
    def phase(self) -> str: return self._current_phase
    @property
    def current_index(self) -> int: return self._current_index
    @property
    def current_question(self) -> Optional[Question]:
        if 0 < self._current_index <= len(self.questions): return self.questions[self._current_index - 1]
        return None

    def pause(self):
        if self._current_phase in ("answering","between","result"): self._pause_event.clear(); logger.info("Admin: 暂停")
    def resume(self): self._pause_event.set(); logger.info("Admin: 恢复")
    def skip(self): self._skip_current = True; logger.info("Admin: 跳过")
    def reveal(self): self._reveal_now = True; logger.info("Admin: 揭晓")
    def next_question(self): self._next_event.set(); logger.info("Admin: 下一题")

    def to_api_state(self) -> dict:
        q = self.current_question
        return {"phase": self._current_phase, "current_index": self._current_index,
                "total_questions": len(self.questions), "question": q.question if q else None,
                "options": q.options if q else [], "answer": q.answer if q else None,
                "explanation": q.explanation if q else "", "category": q.category if q else "",
                "points": q.points if q else 0}

    def load_questions(self, path: str = "data/questions.json"):
        with open(path, "r", encoding="utf-8") as f: raw = json.load(f)
        if not isinstance(raw, list) or not raw: raise ValueError("题库为空或格式错误")
        self.questions = [Question(**q) for q in raw]; random.shuffle(self.questions)

    def on_state_change(self, handler): self._on_state = handler

    async def _emit(self, **kwargs):
        if self._on_state:
            try:
                q = self.current_question
                kw = dict(question=q, total_questions=len(self.questions), current_index=self._current_index)
                if q: kw['category'] = q.category
                kw.update(kwargs)
                await self._on_state(QuizState(**kw))
            except Exception: logger.exception("状态回调异常")

    async def run(self):
        if not self.questions: await self._emit(phase="idle", message="题库为空"); return
        self._current_phase = "countdown"; self._current_index = 0
        for sec in (3,2,1): await self._emit(phase="countdown", time_left=sec, message=f"答题即将开始... {sec}"); await asyncio.sleep(1)
        for i, q in enumerate(self.questions):
            self._current_index = i+1; self._skip_current = False; self._reveal_now = False
            self._current_phase = "answering"; await self._emit(phase="answering", time_left=config.QUESTION_TIME)
            await self._run_timer(config.QUESTION_TIME)
            if self._skip_current: continue
            self._current_phase = "result"
            await self._emit(phase="result", time_left=config.RESULT_DISPLAY,
                             message=f"正确答案: {q.answer} ({q.points}分)",
                             explanation=q.explanation)
            await self._run_timer(config.RESULT_DISPLAY)
        self._current_phase = "finished"; await self._emit(phase="finished", time_left=0, message="答题结束！")

    async def _run_timer(self, seconds: int):
        self._timer = CountdownTimer(seconds, on_tick=self._on_tick); await self._timer.start(); await self._pause_event.wait()

    async def _on_tick(self, remaining: int):
        if self._skip_current or self._reveal_now:
            if self._timer: self._timer.stop()
            return
        if not self._pause_event.is_set(): await self._pause_event.wait()
        if self._on_state:
            q = self.current_question
            kwargs = dict(question=q, time_left=remaining,
                          phase=self._current_phase, total_questions=len(self.questions),
                          current_index=self._current_index)
            if q:
                kwargs['category'] = q.category
                if self._current_phase == 'result':
                    kwargs['explanation'] = q.explanation
            await self._on_state(QuizState(**kwargs))

    def check_answer(self, user_answer: str) -> bool:
        if self._current_index < 1 or self._current_index > len(self.questions): return False
        q = self.questions[self._current_index-1]; raw = user_answer.strip().upper()
        ans = raw[0] if raw and raw[0] in "ABCD123" else ""
        if not ans: return False
        expected = q.answer.strip().upper()
        if ans.isdigit(): ans = chr(ord("A")+int(ans)-1)
        if expected.isdigit(): expected = chr(ord("A")+int(expected)-1)
        return ans == expected

    def check_answer_points(self, user_answer: str) -> int:
        return self.current_question.points if self.check_answer(user_answer) else 0
