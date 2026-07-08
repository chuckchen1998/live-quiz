"""展示模块 — WebSocket + HTTP + Admin API，供OBS浏览器源使用"""

import json
import logging
import os
import time
from typing import Optional

import aiohttp.web
import config

logger = logging.getLogger(__name__)

# 存储所有连接的 WebSocket 客户端
_WS_CLIENTS: set[aiohttp.web.WebSocketResponse] = set()

# Admin API 引用的引擎（main.py 注入）
_engine: Optional["QuizEngine"] = None
# 统计收集器（main.py 注入）
_stats: Optional["StatsCollector"] = None

# 广播节流
_last_broadcast = 0.0


def set_engine(engine: "QuizEngine"):
    """注入答题引擎引用（供 Admin API 使用）"""
    global _engine
    _engine = engine


def set_stats(stats: "StatsCollector"):
    """注入统计收集器引用（供 Admin API 使用）"""
    global _stats
    _stats = stats


async def broadcast(data: dict):
    """向所有 WebSocket 客户端推送数据（自动节流：最小间隔 0.25s）"""
    global _last_broadcast
    now = time.monotonic()
    # 投票期间的快速更新也做节流，但状态变化（phase 切换）不节流
    if data.get("phase") == "answering" and now - _last_broadcast < config.BROADCAST_INTERVAL:
        return
    _last_broadcast = now

    msg = json.dumps(data, ensure_ascii=False)
    dead = []
    for ws in _WS_CLIENTS:
        try:
            await ws.send_str(msg)
        except Exception:
            logger.warning("WebSocket 发送失败，移除客户端", exc_info=True)
            dead.append(ws)
    for ws in dead:
        _WS_CLIENTS.discard(ws)


async def broadcast_force(data: dict):
    """强制广播（不受节流限制，用于 phase 切换）"""
    msg = json.dumps(data, ensure_ascii=False)
    dead = []
    for ws in _WS_CLIENTS:
        try:
            await ws.send_str(msg)
        except Exception:
            logger.warning("WebSocket 发送失败", exc_info=True)
            dead.append(ws)
    for ws in dead:
        _WS_CLIENTS.discard(ws)


# ── HTTP / WebSocket handlers ──

async def ws_handler(request):
    """WebSocket 连接处理"""
    if len(_WS_CLIENTS) >= config.MAX_WS_CONNECTIONS:
        logger.warning(f"WebSocket 连接数已达上限 {config.MAX_WS_CONNECTIONS}")
        ws = aiohttp.web.WebSocketResponse()
        await ws.prepare(request)
        await ws.close(code=1013, message=b"too many connections")
        return ws

    ws = aiohttp.web.WebSocketResponse()
    await ws.prepare(request)
    _WS_CLIENTS.add(ws)
    try:
        async for _ in ws:
            pass
    finally:
        _WS_CLIENTS.discard(ws)
    return ws


async def http_index(request):
    """提供 overlay.html"""
    html_path = os.path.join(os.path.dirname(__file__), "overlay.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return aiohttp.web.Response(text=f.read(), content_type="text/html")


# ── Admin API ──

async def api_health(request):
    """GET /api/health — 健康检查"""
    return aiohttp.web.json_response({
        "status": "ok",
        "phase": _engine.phase if _engine else "unknown",
        "connections": len(_WS_CLIENTS),
        "question": f"{_engine.current_index}/{len(_engine.questions)}"
            if _engine and _engine.questions else "N/A",
    })


async def api_state(request):
    """GET /api/state — 当前状态"""
    if not _engine:
        return aiohttp.web.json_response({"error": "引擎未初始化"}, status=503)
    return aiohttp.web.json_response(_engine.to_api_state())


async def api_pause(request):
    """POST /api/pause"""
    if _engine:
        _engine.pause()
    return aiohttp.web.json_response({"ok": True})


async def api_resume(request):
    """POST /api/resume"""
    if _engine:
        _engine.resume()
    return aiohttp.web.json_response({"ok": True})


async def api_skip(request):
    """POST /api/skip"""
    if _engine:
        _engine.skip()
    return aiohttp.web.json_response({"ok": True})


async def api_reveal(request):
    """POST /api/reveal"""
    if _engine:
        _engine.reveal()
    return aiohttp.web.json_response({"ok": True})


async def api_next(request):
    """POST /api/next"""
    if _engine:
        _engine.next_question()
    return aiohttp.web.json_response({"ok": True})


async def api_leaderboard(request):
    """GET /api/leaderboard — 排行榜"""
    if not _stats:
        return aiohttp.web.json_response({"leaderboard": []})
    return aiohttp.web.json_response({"leaderboard": _stats.leaderboard()})


async def api_user_stats(request):
    """GET /api/user/{user_id} — 个人统计"""
    user_id = request.match_info.get("user_id", "")
    if not _stats or not user_id:
        return aiohttp.web.json_response({"error": "未找到"}, status=404)
    detail = _stats.user_detail(user_id)
    if not detail:
        return aiohttp.web.json_response({"error": "用户不存在"}, status=404)
    return aiohttp.web.json_response(detail)


# ── Admin 控制台页面 ──

_ADMIN_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>直播答题 - 控制台</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:'Microsoft YaHei',sans-serif;background:#1a1a2e;color:#eee;padding:20px}
  h1{text-align:center;margin-bottom:20px;color:#ffd93d}
  #state{background:#16213e;border-radius:12px;padding:16px;margin-bottom:16px;font-size:14px}
  .btn-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
  button{padding:18px;font-size:18px;border:none;border-radius:12px;cursor:pointer;font-weight:bold;transition:.15s}
  button:active{transform:scale(.96)}
  .btn-start{background:#00cec9;color:#1a1a2e;grid-column:span 2}
  .btn-pause{background:#ffd93d;color:#1a1a2e}
  .btn-resume{background:#00cec9;color:#1a1a2e}
  .btn-skip{background:#ff6b6b;color:#fff}
  .btn-reveal{background:#6c5ce7;color:#fff}
  .btn-next{background:#0984e3;color:#fff}
  #log{background:#0f0f23;border-radius:12px;padding:12px;margin-top:16px;max-height:200px;overflow-y:auto;font-family:monospace;font-size:12px;color:#888}
</style>
</head>
<body>
<h1>🎮 直播答题控制台</h1>
<div id="state">连接中...</div>
<div class="btn-grid">
  <button class="btn-pause" onclick="api('pause')">⏸ 暂停</button>
  <button class="btn-resume" onclick="api('resume')">▶ 恢复</button>
  <button class="btn-skip" onclick="api('skip')">⏭ 跳过</button>
  <button class="btn-reveal" onclick="api('reveal')">👁 揭晓</button>
  <button class="btn-next" onclick="api('next')">➡ 下一题</button>
</div>
<div id="log"></div>
<script>
async function api(action) {
  try {
    const r = await fetch('/api/' + action, {method:'POST'});
    const d = await r.json();
    log(`✅ ${action}: ${JSON.stringify(d)}`);
    refresh();
  } catch(e) { log(`❌ ${action}: ${e}`); }
}
async function refresh() {
  try {
    const r = await fetch('/api/state');
    const d = await r.json();
    document.getElementById('state').innerHTML =
      `<b>状态:</b> ${d.phase} | <b>第</b> ${d.current_index}/${d.total_questions} 题<br>
       <b>题目:</b> ${d.question||'—'}<br><b>答案:</b> ${d.answer||'—'}`;
  } catch(e) {}
}
function log(msg) {
  const el = document.getElementById('log');
  el.innerHTML += `<div>${new Date().toLocaleTimeString()} ${msg}</div>`;
  el.scrollTop = el.scrollHeight;
}
setInterval(refresh, 2000);
refresh();
</script>
</body>
</html>"""


async def admin_panel(request):
    """GET /admin — 控制台页面"""
    return aiohttp.web.Response(text=_ADMIN_HTML, content_type="text/html")


# ── 启动 ──

async def start_display():
    """启动展示服务

    Returns:
        AppRunner: 调用 runner.cleanup() 关闭服务
    """
    app = aiohttp.web.Application()
    app.router.add_get("/", http_index)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/admin", admin_panel)
    app.router.add_get("/api/health", api_health)
    app.router.add_get("/api/state", api_state)
    app.router.add_post("/api/pause", api_pause)
    app.router.add_post("/api/resume", api_resume)
    app.router.add_post("/api/skip", api_skip)
    app.router.add_post("/api/reveal", api_reveal)
    app.router.add_post("/api/next", api_next)
    app.router.add_get("/api/leaderboard", api_leaderboard)
    app.router.add_get("/api/user/{user_id}", api_user_stats)

    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, config.DISPLAY_HOST, config.DISPLAY_PORT)
    await site.start()
    logger.info(f"OBS 浏览器源: http://{config.DISPLAY_HOST}:{config.DISPLAY_PORT}")
    logger.info(f"Admin 控制台: http://{config.DISPLAY_HOST}:{config.DISPLAY_PORT}/admin")
    print(f"[展示] OBS 浏览器源: http://{config.DISPLAY_HOST}:{config.DISPLAY_PORT}")
    print(f"[展示] Admin 控制台: http://{config.DISPLAY_HOST}:{config.DISPLAY_PORT}/admin")
    return runner
