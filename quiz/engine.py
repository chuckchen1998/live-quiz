"""答题引擎 — 出题、判题、调度、Admin 控制"""

import asyncio
import json
import logging
import random
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable

import config
from .timer import CountdownTimer

logger = logging.getLogger(__name__)


@dataclass
class Question:
    """一道题"""
    id: int
    question: str
    options: list[str]
    answer: str  # "A" / "B" / "C"


@dataclass
class QuizState:
    """当前答题状态 — 推送给展示模块"""
    question: Optional[Question] = None
    time_left: int = 0
    phase: str = "idle"         # idle | countdown | answering | result | between | paused | finished
    total_questions: int = 0
    current_index: int = 0      # 当前第几题(1-based)
    message: str = ""


class QuizEngine:
    """答题核心引擎 — 支持 Admin API 控制"""

    def __init__(self):
        self.questions: list[Question] = []
        self._timer: Optional[CountdownTimer] = None
        self._current_index = 0
        self._current_phase = "idle"
        self._on_state: Optional[Callable[[QuizState], Awaitable[None]]] = None

        # Admin 控制信号
        self._pause_event = asyncio.Event()
        self._pause_event.set()          # 初始未暂停
        self._skip_current = False       # 跳过当前题
        self._reveal_now = False         # 立即揭晓答案
        self._next_event = asyncio.Event()  # 手动推进到下一题（设为自动模式则始终 set）

    @property
    def phase(self) -> str:
        return self._current_phase

    @property
    def current_index(self) -> int:
        return self._current_index

    # ── Admin API ──

    def pause(self):
        """暂停答题"""
        if self._current_phase in ("answering", "between", "result"):
            self._pause_event.clear()
            logger.info("Admin: 暂停")

    def resume(self):
        """恢复答题"""
        self._pause_event.set()
        logger.info("Admin: 恢复")

    def skip(self):
        """跳过当前题"""
        self._skip_current = True
        if self._timer and self._timer.running:
            self._timer.stop()
        logger.info("Admin: 跳过当前题")

    def reveal(self):
        """立即揭晓答案"""
        self._reveal_now = True
        if self._timer and self._timer.running:
            self._timer.stop()
        logger.info("Admin: 揭晓答案")

    def next_question(self):
        """手动推进到下一题（between 阶段跳过等待）"""
        self._next_event.set()
        if self._timer and self._timer.running:
            self._timer.stop()

    def to_api_state(self) -> dict:
        """导出 Admin API 状态"""
        q = self.questions[self._current_index - 1] \
            if 0 < self._current_index <= len(self.questions) else None
        return {
            "phase": self._current_phase,
            "current_index": self._current_index,
            "total_questions": len(self.questions),
            "question": q.question if q else None,
            "options": q.options if q else [],
            "answer": q.answer if q else None,
        }

    # ── 核心方法 ──

    def load_questions(self, path: str = "data/questions.json"):
        """从 JSON 加载题库

        Raises:
            FileNotFoundError: 题库文件不存在
            json.JSONDecodeError: JSON 格式错误
            ValueError: 题目数据字段不完整
        """
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, list) or not raw:
            raise ValueError("题库为空或格式错误")
        self.questions = [Question(**q) for q in raw]
        random.shuffle(self.questions)

    def on_state_change(self, handler: Callable[[QuizState], Awaitable[None]]):
        """注册状态变化回调"""
        self._on_state = handler

    async def _emit(self, **kwargs):
        """推送状态变化到注册的回调"""
        if self._on_state:
            try:
                await self._on_state(QuizState(
                    question=self.questions[self._current_index - 1]
                        if 0 < self._current_index <= len(self.questions) else None,
                    total_questions=len(self.questions),
                    current_index=self._current_index,
                    **kwargs,
                ))
            except Exception:
                logger.exception("状态回调异常")

    async def run(self):
        """运行完整答题流程（支持 Admin 控制）"""
        if not self.questions:
            await self._emit(phase="idle", message="题库为空")
            return

        # 开场倒计时
        self._current_phase = "countdown"
        self._current_index = 0
        for sec in (3, 2, 1):
            await self._emit(phase="countdown", time_left=sec,
                             message=f"答题即将开始... {sec}")
            await asyncio.sleep(1)

        for i, q in enumerate(self.questions):
            self._current_index = i + 1
            self._skip_current = False
            self._reveal_now = False

            # ① 出题
            self._current_phase = "answering"
            await self._emit(phase="answering", time_left=config.QUESTION_TIME)
            await self._run_timer(config.QUESTION_TIME)

            if self._skip_current:
                logger.info(f"跳过第 {self._current_index} 题")
                continue

            # ② 公布答案 + 停留
            self._current_phase = "result"
            was_revealed = self._reveal_now
            await self._emit(phase="result", time_left=config.RESULT_DISPLAY,
                             message=f"正确答案: {q.answer}")
            await self._run_timer(config.RESULT_DISPLAY)
            self._reveal_now = False

            # ③ 题间休息（最后一题跳过）
            if i < len(self.questions) - 1:
                self._current_phase = "between"
                self._next_event.clear()
                await self._emit(phase="between", time_left=config.BETWEEN_QUESTIONS,
                                 message="下一题即将开始...")
                # 等待间隔结束或手动 next
                try:
                    await asyncio.wait_for(
                        self._next_event.wait(),
                        timeout=config.BETWEEN_QUESTIONS,
                    )
                except asyncio.TimeoutError:
                    pass

        self._current_phase = "finished"
        await self._emit(phase="finished", time_left=0, message="答题结束！")

    async def _run_timer(self, seconds: int):
        """运行倒计时，支持暂停/跳过/揭晓中断"""
        self._timer = CountdownTimer(seconds, on_tick=self._on_tick)
        await self._timer.start()
        # 等待暂停恢复
        await self._pause_event.wait()

    async def _on_tick(self, remaining: int):
        """每秒回调 — 支持跳过/揭晓/暂停"""

        # 检查 Admin 中断信号
        if self._skip_current or self._reveal_now:
            if self._timer:
                self._timer.stop()
            return

        # 检查暂停
        if not self._pause_event.is_set():
            await self._pause_event.wait()

        if self._on_state:
            q = self.questions[self._current_index - 1] \
                if 0 < self._current_index <= len(self.questions) else None
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
        raw = user_answer.strip().upper()
        ans = raw[0] if raw and raw[0] in "ABCD123" else ""
        if not ans:
            return False
        expected = q.answer.strip().upper()
        if ans.isdigit():
            ans = chr(ord("A") + int(ans) - 1)
        if expected.isdigit():
            expected = chr(ord("A") + int(expected) - 1)
        return ans == expected
