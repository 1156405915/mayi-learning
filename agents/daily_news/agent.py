"""
每日新闻简报 Agent 主流程编排模块。
职责：串联「RSSHub 采集清洗 -> 三栏去重合并 -> DeepSeek 编辑简报 -> 飞书消息推送」四步流水线。
"""

from __future__ import annotations

import json

from agents.daily_news.collector import (
    build_subscription_urls,
    collect_all_feeds,
    merge_feeds,
)
from agents.daily_news.prompts import DAILY_NEWS_SYSTEM_PROMPT, build_user_prompt
from core.config import Settings, get_logger
from core.llm import LLMClient
from core.notify.feishu import FeishuNotifier

logger = get_logger("agents.daily_news")


def run(
    settings: Settings | None = None,
    *,
    dry_run: bool = False,
    collect_only: bool = False,
) -> str:
    """
    执行每日新闻简报 Agent 全流程。
    输入：
      - settings：全局配置对象，缺省时自动从环境变量/.env 加载
      - dry_run：为 True 时仅生成并在控制台打印简报，不调用飞书接口发送
      - collect_only：为 True 时仅测试 RSSHub 采集与去重合并，不调用大模型与飞书
    输出：最终生成的简报正文（collect_only 模式下返回格式化后的合并 JSON）。
    """
    cfg = settings or Settings.from_env()
    urls = build_subscription_urls(cfg.rsshub_base_url)

    logger.info("[1/4] 开始并发拉取 %s 个 RSSHub 订阅源...", len(urls))
    parsed_results = collect_all_feeds(urls)

    logger.info("[2/4] 合并并去重各栏目新闻...")
    merged_json = merge_feeds(parsed_results, urls)

    if collect_only:
        pretty = json.dumps(json.loads(merged_json), ensure_ascii=False, indent=2)
        print("\n========== 采集与合并结果（collect-only） ==========\n")
        print(pretty)
        print("\n====================================================\n")
        return pretty

    logger.info("[3/4] 正在调用大模型 (%s) 生成简报...", cfg.llm_model)
    llm = LLMClient(cfg)
    briefing_text = llm.chat(
        system_prompt=DAILY_NEWS_SYSTEM_PROMPT,
        user_prompt=build_user_prompt(merged_json),
        temperature=0.7,
    )

    print("\n========== 生成的简报内容 ==========\n")
    print(briefing_text)
    print("\n====================================\n")

    if dry_run:
        logger.info("[4/4] 当前为 --dry-run 模式，已跳过飞书消息推送。")
        return briefing_text

    logger.info("[4/4] 正在推送简报到飞书...")
    notifier = FeishuNotifier(cfg)
    notifier.send_text(briefing_text)
    logger.info("每日新闻简报执行完毕。")
    return briefing_text
