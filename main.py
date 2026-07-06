#!/usr/bin/env python3
"""直播答题系统 — 主入口

启动顺序:
  1. 展示模块 (HTTP + WebSocket)
  2. 加载题库
  3. 启动评论模拟器
  4. 主循环: 评论 → 判题 → 统计 → 推送
"""

import asyncio

import config
from comment.simulator import SimulatorSource
from quiz.engine import QuizEngine, QuizState
from stats.collector import StatsCollector
from display.server import start_display, broadcast


async def main():
    print("=" * 50)
    print("  直播答题系统 (方案B)")
    print("=" * 50)

    # ── 1. 启动展示服务 ──
    runner = await start_display()

    # ── 2. 加载题库 & 初始化引擎 ──
    engine = QuizEngine()
    engine.load_questions(config.QUESTION_FILE)
    print(f"[系统] 已加载 {len(engine.questions)} 道题目")

    # ── 3. 初始化统计 ──
    stats = StatsCollector()

    # ── 4. 启动模拟评论源 ──
    comment_source = SimulatorSource(
        correct_rate=config.CORRECT_RATE,
        interval=config.COMMENT_INTERVAL,
    )
    await comment_source.start()
    print(f"[系统] 模拟评论源已启动 (间隔 {config.COMMENT_INTERVAL}s)")

    # ── 5. 注册引擎状态回调 ──
    async def on_quiz_state(state: QuizState):
        """当答题引擎状态变化时触发"""
        if state.phase == "answering" and state.question:
            # 新题开始
            stats.new_question(
                question_id=state.question.id,
                question_text=state.question.question,
                options=state.question.options,
                correct=state.question.answer,
            )

        elif state.phase == "result":
            stats.set_phase("result")

        elif state.phase == "between":
            stats.set_phase("between")

        elif state.phase == "idle":
            stats.set_phase("idle")

        # 每次状态变化都推送到前端
        payload = stats.to_dict()
        payload["phase"] = state.phase
        payload["time_left"] = state.time_left
        payload["message"] = state.message
        await broadcast(payload)

    engine.on_state_change(on_quiz_state)

    # ── 6. 主循环：评论处理 + 答题调度 ──
    async def comment_loop():
        """持续读取评论并记录投票"""
        while True:
            comment = await comment_source.get_comment()
            if comment is None:
                await asyncio.sleep(0.05)
                continue

            if comment.answer and stats.current and stats.current.phase == "answering":
                # 记录投票
                stats.record_vote(comment.answer)
                # 推送实时统计
                payload = stats.to_dict()
                await broadcast(payload)

    # 并行运行：答题引擎 + 评论处理
    comment_task = asyncio.create_task(comment_loop())
    quiz_task = asyncio.create_task(engine.run())

    # 等待答题完成
    await quiz_task
    comment_task.cancel()

    # ── 7. 清理 ──
    await comment_source.stop()
    await runner.cleanup()
    print("[系统] 答题结束，系统关闭")


if __name__ == "__main__":
    asyncio.run(main())
