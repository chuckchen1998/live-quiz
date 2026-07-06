"""全局配置 — 支持环境变量覆盖"""

import os


def _env_int(key: str, default: int) -> int:
    val = os.getenv(key)
    return int(val) if val else default


def _env_float(key: str, default: float) -> float:
    val = os.getenv(key)
    return float(val) if val else default


def _env_str(key: str, default: str) -> str:
    return os.getenv(key, default)


# ── 答题配置 ──
QUESTION_TIME = _env_int("QUIZ_QUESTION_TIME", 15)          # 每题倒计时（秒）
RESULT_DISPLAY = _env_int("QUIZ_RESULT_DISPLAY", 8)         # 公布答案停留（秒）
BETWEEN_QUESTIONS = _env_int("QUIZ_BETWEEN_QUESTIONS", 5)   # 题间休息（秒）

# ── 模拟评论配置 ──
COMMENT_INTERVAL = _env_float("QUIZ_COMMENT_INTERVAL", 0.3)
CORRECT_RATE = _env_float("QUIZ_CORRECT_RATE", 0.65)

# ── WebSocket / HTTP 展示服务 ──
DISPLAY_HOST = _env_str("QUIZ_DISPLAY_HOST", "127.0.0.1")
DISPLAY_PORT = _env_int("QUIZ_DISPLAY_PORT", 8765)

# ── 性能 / 限流 ──
BROADCAST_INTERVAL = _env_float("QUIZ_BROADCAST_INTERVAL", 0.25)  # 广播最小间隔（秒）
MAX_WS_CONNECTIONS = _env_int("QUIZ_MAX_WS_CONNECTIONS", 200)     # 最大连接数

# ── 日志 ──
LOG_LEVEL = _env_str("QUIZ_LOG_LEVEL", "INFO")

# ── 数据文件 ──
QUESTION_FILE = _env_str("QUIZ_QUESTION_FILE", "data/questions.json")
RESULT_FILE = _env_str("QUIZ_RESULT_FILE", "data/results.json")

# ── 评论源配置 ──
COMMENT_SOURCE = _env_str("QUIZ_COMMENT_SOURCE", "simulator")  # "simulator" | "douyin"
DOUYIN_ROOM_ID = _env_str("QUIZ_DOUYIN_ROOM_ID", "")           # 抖音直播间 ID
DOUYIN_COOKIE = _env_str("QUIZ_DOUYIN_COOKIE", "")             # 抖音 Cookie（敏感）
