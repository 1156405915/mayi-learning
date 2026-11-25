#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agent-learning 多 Agent 统一命令行与定时调度入口。
支持三种运行方式：
  1. 查看所有已注册 Agent：   python main.py list
  2. 手动单次运行指定 Agent： python main.py run daily_news [--dry-run] [--collect-only]
  3. 启动容器常驻定时调度器： python main.py serve [--config schedules.yaml]
"""

from __future__ import annotations

import argparse
from pathlib import Path
import signal
import sys

from agents.registry import AGENT_REGISTRY, execute_agent, get_agent
from core.config import PROJECT_ROOT, Settings, get_logger

logger = get_logger("main")


def cmd_list() -> int:
    """打印当前项目中已注册的所有 Agent 列表及其默认定时配置。"""
    print(f"{'标识 (Name)':<16} {'默认 Cron':<14} {'名称与说明'}")
    print("-" * 76)
    for spec in AGENT_REGISTRY.values():
        print(f"{spec.name:<16} {spec.default_cron:<14} {spec.title} - {spec.description}")
    return 0


def cmd_run(agent_name: str, dry_run: bool, collect_only: bool) -> int:
    """手动触发单个 Agent 立即执行一次，便于本地开发调试与线上临时补发。"""
    settings = Settings.from_env()
    spec = get_agent(agent_name)
    logger.info(
        "手动启动 Agent: %s (%s) | dry_run=%s | collect_only=%s",
        spec.name,
        spec.title,
        dry_run,
        collect_only,
    )
    execute_agent(
        agent_name,
        settings=settings,
        dry_run=dry_run,
        collect_only=collect_only,
    )
    return 0


def _load_schedule_config(config_path: Path) -> dict:
    """读取 schedules.yaml 定时任务配置文件。"""
    import yaml

    if not config_path.is_file():
        raise FileNotFoundError(f"找不到定时配置文件: {config_path}")
    return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}


def _safe_scheduled_run(agent_name: str) -> None:
    """
    定时任务安全包装器：捕获单次运行异常并记录错误日志，防止单个 Agent 偶发报错拖垮整个调度进程。
    """
    try:
        settings = Settings.from_env()
        logger.info("定时触发 Agent 开始执行: %s", agent_name)
        execute_agent(agent_name, settings=settings)
    except Exception:
        logger.exception("定时任务执行异常 | agent=%s", agent_name)


def cmd_serve(config_file: str) -> int:
    """
    启动基于 APScheduler 的常驻进程调度器，作为 Docker 容器主进程托管所有定时 Agent。
    """
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    settings = Settings.from_env()
    cfg_path = Path(config_file)
    if not cfg_path.is_absolute():
        cfg_path = PROJECT_ROOT / cfg_path

    schedule_data = _load_schedule_config(cfg_path)
    tz = schedule_data.get("timezone") or settings.timezone
    jobs_cfg: dict = schedule_data.get("jobs") or {}

    scheduler = BlockingScheduler(timezone=tz)
    registered_count = 0

    for agent_name, item in jobs_cfg.items():
        if not isinstance(item, dict) or not item.get("enabled", True):
            logger.info("跳过已禁用的定时 Agent: %s", agent_name)
            continue

        spec = get_agent(agent_name)
        cron_expr = str(item.get("cron") or spec.default_cron).strip()
        trigger = CronTrigger.from_crontab(cron_expr, timezone=tz)

        scheduler.add_job(
            _safe_scheduled_run,
            trigger=trigger,
            args=[agent_name],
            id=agent_name,
            name=spec.title,
            replace_existing=True,
            # 允许最多延迟 5 分钟补跑，且同一 Agent 不并发重叠执行
            misfire_grace_time=300,
            max_instances=1,
            coalesce=True,
        )
        registered_count += 1
        logger.info("已装载定时任务 | agent=%s (%s) | cron='%s' | tz=%s", agent_name, spec.title, cron_expr, tz)

    if registered_count == 0:
        logger.warning("当前没有任何启用的定时任务，请检查 %s", cfg_path)

    # 优雅响应 Docker stop 发送的 SIGTERM 信号
    def _shutdown(signum: int, _frame: object) -> None:
        logger.info("收到退出信号 (%s)，正在停止调度器...", signum)
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("多 Agent 定时调度器已就绪（共 %s 个任务），等待触发中...", registered_count)
    scheduler.start()
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description="agent-learning 多 Agent 统一运行与调度入口",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="列出所有已注册的 Agent")

    run_parser = subparsers.add_parser("run", help="立即手动执行一次指定的 Agent")
    run_parser.add_argument("agent", help="要运行的 Agent 标识（例如 daily_news）")
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="试运行模式：正常采集并调用 LLM 生成结果，但跳过飞书推送",
    )
    run_parser.add_argument(
        "--collect-only",
        action="store_true",
        help="仅采集模式：只测试数据源拉取、清洗与去重，不调用 LLM 与飞书",
    )

    serve_parser = subparsers.add_parser("serve", help="启动常驻定时调度器（Docker 容器默认入口）")
    serve_parser.add_argument(
        "--config",
        default="schedules.yaml",
        help="定时任务配置文件路径（默认 schedules.yaml）",
    )
    return parser


def main() -> int:
    """CLI 主入口。"""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "list":
        return cmd_list()
    if args.command == "run":
        return cmd_run(args.agent, dry_run=args.dry_run, collect_only=args.collect_only)
    if args.command == "serve":
        return cmd_serve(args.config)
    return 1


if __name__ == "__main__":
    sys.exit(main())
