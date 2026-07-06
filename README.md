# 🎮 直播答题系统 (Live Quiz System)

> 方案 B — 模块化 Python 直播答题系统，用于直播间实时评论答题互动。

基于 `asyncio` + `aiohttp`，模拟弹幕 + 出题判题 + 实时统计 + OBS 浏览器源展示。

---

## 📁 项目结构

```
live-quiz/
├── main.py                 # 入口：启动所有模块
├── config.py               # 全局配置（倒计时、端口、题库路径等）
├── requirements.txt        # Python 依赖
├── data/
│   └── questions.json      # 题库（JSON 格式）
├── comment/                # ① 评论模块
│   ├── base.py             #    抽象基类 CommentSource（后期替换真实数据源）
│   └── simulator.py        #    模拟评论生成器（开发/测试用）
├── quiz/                   # ② 答题模块
│   ├── engine.py           #    核心引擎：加载题库 → 出题 → 倒计时 → 公布答案
│   └── timer.py            #    异步倒计时器（支持提前终止）
├── stats/                  # ③ 统计模块
│   └── collector.py        #    实时收集投票 → 汇总 A/B/C 分布
└── display/                # ④ 展示模块
    ├── server.py           #    aiohttp HTTP + WebSocket 服务
    └── overlay.html        #    OBS 浏览器源页面（深色 UI + 实时柱状图）
```

---

## 🚀 快速开始

### 环境要求

- Python 3.10+
- pip

### 安装 & 运行

```bash
# 1. 克隆仓库
git clone https://github.com/chuckchen1998/live-quiz.git
cd live-quiz

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动系统
python main.py
```

启动后控制台输出：

```
[展示] OBS 浏览器源: http://127.0.0.1:8765
[展示] WebSocket: ws://127.0.0.1:8765/ws
[系统] 已加载 5 道题目
[系统] 模拟评论源已启动 (间隔 0.3s)
```

### OBS 配置

1. 添加 **浏览器** 源
2. URL 填入 `http://127.0.0.1:8765`
3. 宽度 800，高度 600（可调整）

---

## 🔧 配置说明

编辑 `config.py`：

| 参数 | 默认值 | 说明 |
|:---|:---:|:---|
| `QUESTION_TIME` | 15 | 每题倒计时（秒） |
| `BETWEEN_QUESTIONS` | 5 | 题间间隔（秒） |
| `COMMENT_INTERVAL` | 0.3 | 模拟评论生成间隔（秒） |
| `CORRECT_RATE` | 0.65 | 模拟正确率 |
| `DISPLAY_HOST` | 127.0.0.1 | 展示服务地址 |
| `DISPLAY_PORT` | 8765 | 展示服务端口 |

---

## 🧩 架构设计

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  ① 评论模块   │ ──→ │  ② 答题模块   │ ──→ │  ③ 统计模块   │ ──→ │  ④ 展示模块   │
│  simulator   │     │  engine.py   │     │  collector   │     │  server.py   │
│  模拟弹幕     │     │  出题/判题    │     │  投票汇总     │     │  WebSocket   │
│              │     │  倒计时       │     │  实时统计     │     │  OBS 浏览器源 │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
```

### 数据流

1. **评论模块** 生成模拟弹幕（可替换为真实直播平台评论源）
2. **答题引擎** 按题库顺序出题，进入答题阶段后接收评论中的 A/B/C 答案
3. **统计模块** 实时汇总每个选项的票数
4. **展示模块** 通过 WebSocket 推送数据到 OBS 浏览器源，前端渲染柱状图

### 阶段状态机

```
idle → answering（出题+倒计时）→ result（公布答案）→ between（题间休息）→ answering → ...
```

---

## 🔄 替换真实数据源

实现 `comment/simulator.py` 的 `CommentSource` 接口即可：

```python
from comment.base import CommentSource, Comment

class LivePlatformSource(CommentSource):
    async def start(self):
        # 连接直播平台 WebSocket / API
        ...

    async def get_comment(self) -> Optional[Comment]:
        # 从真实弹幕流获取一条评论
        return Comment(user="观众A", text="B", answer="B")

    async def stop(self):
        # 断开连接
        ...
```

然后在 `main.py` 中替换 `SimulatorSource` 为你的实现。

---

## 📝 题库格式

`data/questions.json`：

```json
[
    {
        "id": 1,
        "question": "Python 中，以下哪个是可变数据类型？",
        "options": ["A. 字符串", "B. 列表", "C. 元组"],
        "answer": "B"
    }
]
```

支持 A/B/C 或 1/2/3 答案格式，引擎自动规范化匹配。

---

## 🖥️ OBS 展示效果

- 深色半透明卡片风格
- 彩色柱状图（红/紫/青/黄）
- 倒计时数字闪烁提示（≤5 秒变红）
- 答题结束后显示正确答案 + 正确率
- 实时参与人数统计

---

## 📄 License

MIT
