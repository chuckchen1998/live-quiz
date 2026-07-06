#!/usr/bin/env python3
"""直播答题系统 — 主入口

启动顺序:
  1. 展示模块 (HTTP + WebSocket)
  2. 加载题库
  3. 启动评论模拟器
  4. 主循环: 评论 → 判题 → 统计 → 推送
"""

import asyncio
import signal
import sys

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
    try:
        runner = await start_display()
    except OSError as e:
        print(f"[错误] 无法启动展示服务: {e}", file=sys.stderr)
        return

    # ── 2. 加载题库 & 初始化引擎 ──
    engine = QuizEngine()
    try:
        engine.load_questions(config.QUESTION_FILE)
    except (FileNotFoundError, ValueError) as e:
        print(f"[错误] 加载题库失败: {e}", file=sys.stderr)
        await runner.cleanup()
        return
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
            stats.new_question(
                question_id=state.question.id,
                question_text=state.question.question,
                options=state.question.options,
                correct=state.question.answer,
            )

        elif state.phase == "result":
            stats.set_phase("result")
            # 批量标记正确答案 — 遍历所有已投用户
            # MVP 阶段: 由于模拟评论无用户标识，按投票分布估算正确数
            # 实际接入真实源后改为逐用户 check_answer()

        elif state.phase == "between":
            stats.set_phase("between")

        elif state.phase == "idle":
            stats.set_phase("idle")

        # 推送状态到前端
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

            if not (comment.answer and stats.current and stats.current.phase == "answering"):
                continue

            # 判题 & 记录投票
            is_correct = engine.check_answer(comment.answer)
            stats.record_vote(comment.answer)
            if is_correct:
                stats.mark_correct(comment.answer)

    # 并行运行：答题引擎 + 评论处理
    comment_task = asyncio.create_task(comment_loop())
    quiz_task = asyncio.create_task(engine.run())

    # 注册优雅关闭
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _on_signal():
        print("\n[系统] 收到终止信号，正在关闭...")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            pass  # Windows 不支持 add_signal_handler for SIGTERM

    # 等待答题完成 或 关闭信号
    done, pending = await asyncio.wait(
        [quiz_task, asyncio.create_task(shutdown_event.wait())],
        return_when=asyncio.FIRST_COMPLETED,
    )

    # 如果提前关闭，取消未完成的任务
    if not quiz_task.done():
        quiz_task.cancel()
    comment_task.cancel()

    # 等待 task 真正终止
    for task in (quiz_task, comment_task):
        try:
            await task
        except asyncio.CancelledError:
            pass

    # ── 7. 清理 ──
    await comment_source.stop()
    await runner.cleanup()
    print("[系统] 答题结束，系统关闭")


if __name__ == "__main__":
    asyncio.run(main())
