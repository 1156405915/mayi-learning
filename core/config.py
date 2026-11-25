"""
统一配置加载与日志工厂模块。
职责：兼容本地开发与 Docker 容器环境，自动读取 .env 文件并提供类型化的全局配置。
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv_file(env_path: Path | None = None) -> None:
    """
    轻量级加载项目根目录下的 .env 文件到进程环境变量中。
    业务原因：本地直接运行 python main.py 时无需强依赖 python-dotenv，
    且已存在于系统环境（如 docker-compose env_file 注入）的变量优先级更高，不会被覆盖。
    """
    target = env_path or (PROJECT_ROOT / ".env")
    if not target.is_file():
        return

    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        # 跳过空行与注释行
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        # 去除首尾包裹的单双引号，避免密钥带入多余引号导致鉴权失败
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    """
    全局运行配置对象，集中管理数据源、大模型与消息推送渠道参数。
    """

    timezone: str
    rsshub_base_url: str
    searxng_base_url: str
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    feishu_app_id: str
    feishu_app_secret: str
    feishu_receive_id: str
    feishu_receive_id_type: str
    feishu_webhook_url: str
    feishu_webhook_secret: str

    @classmethod
    def from_env(cls) -> "Settings":
        """
        从环境变量构建配置实例，在读取前自动尝试加载本地 .env 文件。
        """
        load_dotenv_file()
        return cls(
            timezone=os.getenv("TZ", "Asia/Shanghai"),
            rsshub_base_url=os.getenv("RSSHUB_BASE_URL", "http://127.0.0.1:1200").rstrip("/"),
            searxng_base_url=os.getenv("SEARXNG_BASE_URL", "http://127.0.0.1:8181").rstrip("/"),
            llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/"),
            llm_model=os.getenv("LLM_MODEL", "deepseek-chat").strip(),
            feishu_app_id=os.getenv("FEISHU_APP_ID", "").strip(),
            feishu_app_secret=os.getenv("FEISHU_APP_SECRET", "").strip(),
            feishu_receive_id=os.getenv(
                "FEISHU_RECEIVE_ID", "oc_7c47fc54e8d20731953bc3fbc07da00b"
            ).strip(),
            feishu_receive_id_type=os.getenv("FEISHU_RECEIVE_ID_TYPE", "chat_id").strip(),
            feishu_webhook_url=os.getenv("FEISHU_WEBHOOK_URL", "").strip(),
            feishu_webhook_secret=os.getenv("FEISHU_WEBHOOK_SECRET", "").strip(),
        )


def get_logger(name: str) -> logging.Logger:
    """
    创建或获取统一格式的日志记录器，直接输出到标准输出以便 docker logs 实时采集。
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
        logger.propagate = False
    return logger
