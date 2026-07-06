"""展示模块 — WebSocket + HTTP 服务，供OBS浏览器源使用"""

import asyncio
import json
import os
import weakref

import aiohttp.web
import config

# 存储所有连接的 WebSocket 客户端
_WS_CLIENTS: weakref.WeakSet = weakref.WeakSet()


async def broadcast(data: dict):
    """向所有 WebSocket 客户端推送数据"""
    msg = json.dumps(data, ensure_ascii=False)
    dead = []
    for ws in _WS_CLIENTS:
        try:
            await ws.send_str(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _WS_CLIENTS.discard(ws)


async def ws_handler(request):
    """WebSocket 连接处理"""
    ws = aiohttp.web.WebSocketResponse()
    await ws.prepare(request)
    _WS_CLIENTS.add(ws)
    try:
        async for _ in ws:
            pass  # 不处理客户端消息
    finally:
        _WS_CLIENTS.discard(ws)
    return ws


async def http_index(request):
    """提供 overlay.html"""
    html_path = os.path.join(os.path.dirname(__file__), "overlay.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return aiohttp.web.Response(text=f.read(), content_type="text/html")


async def start_display():
    """启动展示服务"""
    app = aiohttp.web.Application()
    app.router.add_get("/", http_index)
    app.router.add_get("/ws", ws_handler)

    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, config.DISPLAY_HOST, config.DISPLAY_PORT)
    await site.start()
    print(f"[展示] OBS 浏览器源: http://{config.DISPLAY_HOST}:{config.DISPLAY_PORT}")
    print(f"[展示] WebSocket: ws://{config.DISPLAY_HOST}:{config.DISPLAY_PORT}/ws")
    return runner
