#!/usr/bin/env python3
"""直播答题系统 — 主入口

启动: python main.py
OBS 浏览器源: http://127.0.0.1:8765
Admin 控制台: http://127.0.0.1:8765/admin

切换评论源:
  QUYZ_COMMENT_SOURCE=simulator python main.py   (默认)
  QUYZ_COMMENT_SOURCE=douyin python main.py      (需配置 DOUYIN_ROOM_ID)
"""

import asyncio
import json
import logging
import signal
import sys
import time

import config
from comment.factory import CommentSourceFactory
from comment.manager import ConnectionManager, CommentEvent
from quiz.engine import QuizEngine, QuizState
from stats.collector import StatsCollector
from display.server import start_display, set_engine, broadcast, broadcast_force

# ── 日志配置 ──
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


async def main():
    logger.info(f"直播答题系统 启动 (评论源: {config.COMMENT_SOURCE})")
    print(f"[系统] 评论源: {config.COMMENT_SOURCE}")

    # ── 1. 启动展示服务 ──
    try:
        runner = await start_display()
    except OSError as e:
        logger.error(f"无法启动展示服务: {e}")
        return

    # ── 2. 加载题库 & 初始化引擎 ──
    engine = QuizEngine()
    try:
        engine.load_questions(config.QUESTION_FILE)
    except (FileNotFoundError, ValueError) as e:
        logger.error(f"加载题库失败: {e}")
        await runner.cleanup()
        return
    logger.info(f"已加载 {len(engine.questions)} 道题目")
    print(f"[系统] 已加载 {len(engine.questions)} 道题目")

    # 注入引擎到 Admin API
    set_engine(engine)

    # ── 3. 创建评论源（工厂） ──
    source_kwargs = _build_source_kwargs()
    comment_source = CommentSourceFactory.create(config.COMMENT_SOURCE, **source_kwargs)

    # ── 4. 连接管理器 ──
    manager = ConnectionManager(comment_source)

    # 连接状态回调
    async def _on_connected():
        logger.info(f"评论源已连接: {comment_source.platform}")

    async def _on_disconnected(reason: str):
        logger.warning(f"评论源断开: {reason}")

    async def _on_error(exc: Exception):
        logger.error(f"评论源错误: {exc}")

    manager.on_connected = _on_connected
    manager.on_disconnected = _on_disconnected
    manager.on_error = _on_error

    connected = await manager.start()
    if not connected:
        logger.error("无法连接评论源，退出")
        await runner.cleanup()
        return
    print(f"[系统] 评论源已连接: {comment_source.platform}")

    # ── 5. 初始化统计 ──
    stats = StatsCollector()

    # ── 6. 注册引擎状态回调 ──
    async def on_quiz_state(state: QuizState):
        if state.phase == "answering" and state.question:
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
        elif state.phase in ("idle", "countdown", "finished"):
            stats.set_phase(state.phase)

        payload = stats.to_dict()
        payload["phase"] = state.phase
        payload["time_left"] = state.time_left
        payload["message"] = state.message
        await broadcast_force(payload)

    engine.on_state_change(on_quiz_state)

    # ── 7. 主循环：评论处理 + 答题调度 ──
    async def comment_loop():
        """持续读取 CommentEvent → 去重投票 → 节流广播"""
        while True:
            event: CommentEvent = await manager.get_comment()
            if event is None:
                await asyncio.sleep(0.05)
                continue

            if not (event.answer and stats.current and stats.current.phase == "answering"):
                continue

            # 去重投票（user_id 去重）
            is_new = stats.record_vote(event.user_id, event.answer)
            if not is_new:
                continue

            # 判题
            if engine.check_answer(event.answer):
                stats.mark_correct(event.user_id, event.answer)

            # 节流广播
            payload = stats.to_dict()
            payload["phase"] = "answering"
            await broadcast(payload)

    # 并行运行
    comment_task = asyncio.create_task(comment_loop())
    quiz_task = asyncio.create_task(engine.run())

    # ── 8. 优雅关闭 ──
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _on_signal():
        logger.info("收到终止信号")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            pass

    done, pending = await asyncio.wait(
        [quiz_task, asyncio.create_task(shutdown_event.wait())],
        return_when=asyncio.FIRST_COMPLETED,
    )

    if not quiz_task.done():
        quiz_task.cancel()
    comment_task.cancel()

    for task in (quiz_task, comment_task):
        try:
            await task
        except asyncio.CancelledError:
            pass

    # ── 9. 保存结果 + 清理 ──
    _save_results(stats, engine)
    await manager.stop()
    await runner.cleanup()
    logger.info("答题结束，系统关闭")
    print("[系统] 答题结束，系统关闭")


def _build_source_kwargs() -> dict:
    """根据 COMMENT_SOURCE 构建工厂参数"""
    if config.COMMENT_SOURCE == "simulator":
        return {
            "correct_rate": config.CORRECT_RATE,
            "interval": config.COMMENT_INTERVAL,
        }
    elif config.COMMENT_SOURCE == "douyin":
        return {
            "room_id": config.DOUYIN_ROOM_ID,
            "cookie": config.DOUYIN_COOKIE,
        }
    return {}


def _save_results(stats: StatsCollector, engine: QuizEngine):
    """保存答题结果到 JSON 文件"""
    results = {
        "total_questions": len(engine.questions),
        "completed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "questions": [],
    }
    for qs in stats.history + ([stats.current] if stats.current else []):
        if qs:
            results["questions"].append({
                "id": qs.question_id,
                "question": qs.question_text,
                "correct_answer": qs.correct_answer,
                "votes": qs.votes,
                "total": qs.total_votes,
                "correct_count": qs.correct_count,
                "accuracy": round(qs.correct_count / max(qs.total_votes, 1) * 100, 1),
            })
    try:
        with open(config.RESULT_FILE, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.info(f"结果已保存: {config.RESULT_FILE}")
    except OSError as e:
        logger.error(f"保存结果失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())
