# 直播答题系统 Docker 镜像
FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码
COPY . .

# 默认使用模拟评论源
ENV QUIZ_COMMENT_SOURCE=simulator
ENV QUIZ_DISPLAY_HOST=0.0.0.0
ENV QUIZ_DISPLAY_PORT=8765

EXPOSE 8765

CMD ["python", "main.py"]
