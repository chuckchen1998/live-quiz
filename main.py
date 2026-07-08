#!/usr/bin/env python3
"""直播答题系统 — 主入口"""

import asyncio, json, logging, signal, sys, time
import config
from comment.factory import CommentSourceFactory
from comment.manager import ConnectionManager, CommentEvent
from quiz.engine import QuizEngine, QuizState
from stats.collector import StatsCollector
from display.server import start_display, set_engine, set_stats, broadcast, broadcast_force

logging.basicConfig(level=getattr(logging,config.LOG_LEVEL,logging.INFO),format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",datefmt="%H:%M:%S")
logger = logging.getLogger("main")

async def main():
    logger.info(f"直播答题系统 启动 (评论源: {config.COMMENT_SOURCE})")
    print(f"[系统] 评论源: {config.COMMENT_SOURCE}")
    try: runner = await start_display()
    except OSError as e: logger.error(f"无法启动展示服务: {e}"); return
    engine = QuizEngine()
    try: engine.load_questions(config.QUESTION_FILE)
    except (FileNotFoundError, ValueError) as e: logger.error(f"加载题库失败: {e}"); await runner.cleanup(); return
    logger.info(f"已加载 {len(engine.questions)} 道题目"); print(f"[系统] 已加载 {len(engine.questions)} 道题目"); set_engine(engine)
    source_kwargs = {}
    if config.COMMENT_SOURCE == "simulator":
        source_kwargs = {"correct_rate": config.CORRECT_RATE, "interval": config.COMMENT_INTERVAL}
    elif config.COMMENT_SOURCE == "douyin-uia":
        source_kwargs = {"interval": config.UIA_INTERVAL}
    comment_source = CommentSourceFactory.create(config.COMMENT_SOURCE, **source_kwargs)
    manager = ConnectionManager(comment_source)
    async def _on_connected(): logger.info(f"评论源已连接: {comment_source.platform}")
    async def _on_disconnected(r): logger.warning(f"评论源断开: {r}")
    async def _on_error(e): logger.error(f"评论源错误: {e}")
    manager.on_connected=_on_connected; manager.on_disconnected=_on_disconnected; manager.on_error=_on_error
    if not await manager.start(): logger.error("无法连接评论源"); await runner.cleanup(); return
    print(f"[系统] 评论源已连接: {comment_source.platform}")
    stats = StatsCollector()
    set_stats(stats)

    async def on_quiz_state(state: QuizState):
        if state.phase=="answering" and state.question:
            q=state.question; stats.new_question(q.id,q.question,q.options,q.answer,points=q.points)
        elif state.phase=="result": stats.set_phase("result")
        elif state.phase=="between": stats.set_phase("between")
        elif state.phase in ("idle","countdown","finished"): stats.set_phase(state.phase)
        payload=stats.to_dict()
        payload["phase"]=state.phase
        payload["time_left"]=state.time_left
        payload["message"]=state.message
        payload["explanation"]=getattr(state,"explanation","")
        payload["category"]=getattr(state,"category","")
        payload["current_index"]=getattr(state,"current_index",0)
        payload["total_questions"]=getattr(state,"total_questions",0)
        await broadcast_force(payload)
    engine.on_state_change(on_quiz_state)

    async def comment_loop():
        vote_count = 0
        skip = 0
        total = 0
        while True:
            event: CommentEvent = await manager.get_comment()
            total += 1
            if event is None:
                if total <= 2: print(f"[DEBUG] get_comment返回None #t{total}")
                await asyncio.sleep(0.05); continue
            if total <= 5:
                print(f"[DEBUG] 弹幕: {event.nickname} | answer={event.answer!r} | content={event.content!r}")
            if not event.answer:
                skip += 1; continue
            if not (stats.current and stats.current.phase=="answering"):
                skip += 1
                if skip <= 3: print(f"[DEBUG] 跳过: phase={stats.current.phase if stats.current else 'None'}, answer={event.answer}")
                continue
            if not stats.record_vote(event.user_id, event.answer): continue
            correct = engine.check_answer(event.answer)
            q_points = engine.current_question.points if engine.current_question else 1
            if correct: stats.mark_correct(event.user_id,event.answer,event.nickname,points=q_points)
            else: stats.mark_correct(event.user_id,event.answer,event.nickname,points=0)
            payload=stats.to_dict(); payload["phase"]="answering"; await broadcast(payload)
            vote_count += 1
            if vote_count <= 3 or vote_count % 20 == 0:
                print(f"[投票 #{vote_count}] {event.nickname}→{event.answer}, total={stats.current.total_votes}, {stats.current.votes}")

    comment_task=asyncio.create_task(comment_loop()); quiz_task=asyncio.create_task(engine.run())
    loop=asyncio.get_running_loop(); shutdown_event=asyncio.Event()
    def _on_signal(): logger.info("收到终止信号"); shutdown_event.set()
    for sig in (signal.SIGINT,signal.SIGTERM):
        try: loop.add_signal_handler(sig,_on_signal)
        except NotImplementedError: pass
    done,pending = await asyncio.wait([quiz_task,asyncio.create_task(shutdown_event.wait())],return_when=asyncio.FIRST_COMPLETED)
    if not quiz_task.done(): quiz_task.cancel()
    comment_task.cancel()
    for task in (quiz_task,comment_task):
        try: await task
        except asyncio.CancelledError: pass
    _save_results(stats,engine); await manager.stop(); await runner.cleanup()
    logger.info("答题结束"); print("[系统] 答题结束")

def _save_results(stats,engine):
    results={"total_questions":len(engine.questions),"completed_at":time.strftime("%Y-%m-%d %H:%M:%S"),"questions":[],"leaderboard":stats.leaderboard(sort_by="points")}
    for qs in stats.history+([stats.current] if stats.current else []):
        if qs: results["questions"].append({"id":qs.question_id,"question":qs.question_text,"correct_answer":qs.correct_answer,"points":qs.points,"votes":qs.votes,"total":qs.total_votes,"correct_count":qs.correct_count,"accuracy":round(qs.correct_count/max(qs.total_votes,1)*100,1)})
    with open(config.RESULT_FILE,"w",encoding="utf-8") as f: json.dump(results,f,ensure_ascii=False,indent=2)

if __name__=="__main__": asyncio.run(main())
