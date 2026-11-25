"""
多 Agent 注册中心。
职责：集中登记项目中所有可用 Agent 的元信息、默认定时策略与执行入口，
新增 Agent 时只需在此处注册一条 AgentSpec，CLI 与定时调度器即可自动识别。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from agents.daily_news.agent import run as run_daily_news
from core.config import Settings


@dataclass(frozen=True)
class AgentSpec:
    """单个 Agent 的标准化注册描述。"""

    name: str
    title: str
    description: str
    default_cron: str
    doc_path: str
    runner: Callable[..., str]


AGENT_REGISTRY: dict[str, AgentSpec] = {
    "daily_news": AgentSpec(
        name="daily_news",
        title="每日新闻简报 Agent",
        description="拉取 RSSHub 政策/财经/科技多源资讯，去重后经 DeepSeek 总结并推送到飞书群。",
        default_cron="0 8 * * *",
        doc_path="docs/agents/01-daily-news.md",
        runner=run_daily_news,
    ),
}


def get_agent(name: str) -> AgentSpec:
    """
    按唯一标识获取已注册的 Agent；名称不存在时给出清晰的可用列表提示。
    """
    if name not in AGENT_REGISTRY:
        available = ", ".join(sorted(AGENT_REGISTRY.keys()))
        raise KeyError(f"未找到名为 '{name}' 的 Agent，当前可用: [{available}]")
    return AGENT_REGISTRY[name]


def execute_agent(
    name: str,
    settings: Settings | None = None,
    *,
    dry_run: bool = False,
    collect_only: bool = False,
) -> str:
    """
    统一调用指定 Agent 的入口函数。
    """
    spec = get_agent(name)
    return spec.runner(settings=settings, dry_run=dry_run, collect_only=collect_only)
