"""全局配置"""

# 答题配置
QUESTION_TIME = 15          # 每题倒计时（秒）
BETWEEN_QUESTIONS = 5       # 题间间隔（秒）

# 模拟评论配置
COMMENT_INTERVAL = 0.3      # 模拟评论发送间隔（秒）
CORRECT_RATE = 0.65         # 模拟正确率

# WebSocket / HTTP 展示服务
DISPLAY_HOST = "127.0.0.1"
DISPLAY_PORT = 8765

# 数据文件
QUESTION_FILE = "data/questions.json"
