"""全局配置 — 支持环境变量覆盖"""
import os
def _env_int(k,d): v=os.getenv(k); return int(v) if v else d
def _env_float(k,d): v=os.getenv(k); return float(v) if v else d
def _env_str(k,d): return os.getenv(k,d)
QUESTION_TIME=_env_int("QUIZ_QUESTION_TIME",15)
RESULT_DISPLAY=_env_int("QUIZ_RESULT_DISPLAY",8)
BETWEEN_QUESTIONS=_env_int("QUIZ_BETWEEN_QUESTIONS",5)
COMMENT_INTERVAL=_env_float("QUIZ_COMMENT_INTERVAL",0.3)
CORRECT_RATE=_env_float("QUIZ_CORRECT_RATE",0.65)
DISPLAY_HOST=_env_str("QUIZ_DISPLAY_HOST","127.0.0.1")
DISPLAY_PORT=_env_int("QUIZ_DISPLAY_PORT",8765)
BROADCAST_INTERVAL=_env_float("QUIZ_BROADCAST_INTERVAL",0.25)
MAX_WS_CONNECTIONS=_env_int("QUIZ_MAX_WS_CONNECTIONS",200)
LOG_LEVEL=_env_str("QUIZ_LOG_LEVEL","INFO")
QUESTION_FILE=_env_str("QUIZ_QUESTION_FILE","data/questions.json")
RESULT_FILE=_env_str("QUIZ_RESULT_FILE","data/results.json")
COMMENT_SOURCE=_env_str("QUIZ_COMMENT_SOURCE","simulator")
DOUYIN_ROOM_ID=_env_str("QUIZ_DOUYIN_ROOM_ID","")
DOUYIN_COOKIE=_env_str("QUIZ_DOUYIN_COOKIE","")
ADMIN_TOKEN=_env_str("QUIZ_ADMIN_TOKEN","")
DOUYIN_WS_URL = _env_str("QUIZ_DOUYIN_WS_URL", "")
# 答题时间（秒）— 可在 questions.json 的 quiz_settings 中覆盖
QUESTION_TIME = _env_int("QUIZ_QUESTION_TIME", 15)
# 结果展示时间（秒）
RESULT_DISPLAY = _env_int("QUIZ_RESULT_DISPLAY", 8)
# 题间间隔（秒）
BETWEEN_QUESTIONS = _env_int("QUIZ_BETWEEN_QUESTIONS", 3)
# UIA 弹幕源轮询间隔（秒）
UIA_INTERVAL = _env_float("QUIZ_UIA_INTERVAL", 1.0)
