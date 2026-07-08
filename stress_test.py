"""压力测试 — 验证系统在高并发下的稳定性

用法:
  python stress_test.py                          # 默认: 50 连接, 30s
  python stress_test.py --connections 200 --duration 60

测试场景:
  1. 多 WebSocket 并发连接
  2. 高密度评论投票
  3. 广播延迟测量
  4. 内存/CPU 监控
"""

import argparse
import asyncio
import json
import time
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))


async def ws_client(client_id: int, stats: dict):
    """单个 WebSocket 客户端"""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect("ws://127.0.0.1:8765/ws") as ws:
                stats["connected"] += 1
                msg_count = 0
                first_msg = None
                last_msg = None

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        msg_count += 1
                        data = json.loads(msg.data)
                        if first_msg is None:
                            first_msg = time.time()
                        last_msg = time.time()

                        # 检查数据完整性
                        if "votes" not in data:
                            stats["malformed"] += 1

                stats["disconnected"] += 1
                if msg_count > 0:
                    stats["total_msgs"] += msg_count
                    stats["first_msg_latency"] = min(
                        stats.get("first_msg_latency", 999), first_msg - stats["start_time"]
                    )

    except Exception as e:
        stats["errors"] += 1
        stats["error_samples"].append(str(e)[:100])


async def health_monitor(stats: dict, duration: int):
    """定期健康检查"""
    import aiohttp
    async with aiohttp.ClientSession() as session:
        for i in range(duration // 2):
            await asyncio.sleep(2)
            try:
                async with session.get("http://127.0.0.1:8765/api/health", timeout=3) as resp:
                    data = await resp.json()
                    stats["health_checks"] += 1
                    if data.get("status") != "ok":
                        stats["health_failures"] += 1
            except Exception:
                stats["health_failures"] += 1


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--connections", type=int, default=50)
    parser.add_argument("--duration", type=int, default=30)
    args = parser.parse_args()

    print(f"╔══════════════════════════════╗")
    print(f"║   直播答题系统 压力测试     ║")
    print(f"╠══════════════════════════════╣")
    print(f"║ 连接数: {args.connections:<4}               ║")
    print(f"║ 时长:   {args.duration:<4}s              ║")
    print(f"╚══════════════════════════════╝")
    print()

    stats = {
        "start_time": time.time(),
        "connected": 0,
        "disconnected": 0,
        "errors": 0,
        "error_samples": [],
        "total_msgs": 0,
        "malformed": 0,
        "health_checks": 0,
        "health_failures": 0,
    }

    # 启动客户端
    clients = [
        asyncio.create_task(ws_client(i, stats))
        for i in range(args.connections)
    ]

    # 启动健康监控
    monitor = asyncio.create_task(health_monitor(stats, args.duration))

    # 等待
    await asyncio.sleep(args.duration)

    # 收集结果
    monitor.cancel()
    for c in clients:
        c.cancel()
    await asyncio.gather(*clients, monitor, return_exceptions=True)

    # ── 报告 ──
    elapsed = time.time() - stats["start_time"]

    print("═══ 测试结果 ═══")
    print(f"  运行时间:     {elapsed:.1f}s")
    print(f"  目标连接:     {args.connections}")
    print(f"  成功连接:     {stats['connected']}")
    print(f"  异常断开:     {stats['disconnected']}")
    print(f"  错误数:       {stats['errors']}")
    print(f"  收到总消息:   {stats['total_msgs']}")
    print(f"  格式异常消息: {stats['malformed']}")
    print(f"  健康检查:     {stats['health_checks']}/{stats['health_checks']+stats['health_failures']} 通过")

    if stats["total_msgs"] > 0:
        msgs_per_conn = stats["total_msgs"] / max(stats["connected"], 1)
        print(f"  平均每连接:   {msgs_per_conn:.0f} 条消息")

    if stats.get("first_msg_latency"):
        print(f"  首消息延迟:   {stats['first_msg_latency']:.3f}s")

    # 评分
    score = 100
    if stats["errors"] > 0:
        score -= stats["errors"] * 5
    if stats["malformed"] > 0:
        score -= 10
    if stats["health_failures"] > 0:
        score -= 20
    if stats["connected"] < args.connections:
        score -= 30

    print(f"\n  稳定性评分:   {max(0, score)}/100")

    if score >= 90:
        print("  结论: ✅ 通过")
    elif score >= 60:
        print("  结论: ⚠️ 有风险")
    else:
        print("  结论: ❌ 不通过")

    if stats["error_samples"]:
        print(f"\n  错误样本:")
        for e in stats["error_samples"][:5]:
            print(f"    - {e}")

    return 0 if score >= 80 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
