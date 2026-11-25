FROM python:3.12-slim

# 确保 Python 日志实时刷出到 docker logs，且不生成无用的 .pyc 缓存文件
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 配置系统时区为北京时间，确保日志时间戳与业务判断一致
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY core ./core
COPY agents ./agents
COPY schedules.yaml main.py ./

# 默认启动常驻定时调度器，托管 schedules.yaml 中启用的所有 Agent
CMD ["python", "main.py", "serve"]
