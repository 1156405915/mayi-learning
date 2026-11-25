"""
每日新闻简报采集与清洗模块。
职责：并发拉取 RSSHub 订阅源（带失败重试）、解析 RSS 2.0 XML、清洗 HTML 标签、转换时区，
并按「中央政策 / 财经快讯 / 科技新闻」三栏去重与生成采集覆盖率报告。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import json
import os
import re
import time
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
import requests

from core.config import get_logger

logger = get_logger("agents.daily_news.collector")

# 订阅路由字典：RSSHub 路由 -> (候选栏目, 来源显示名)
SOURCES: dict[str, tuple[str, str]] = {
    "/gov/zhengce/zuixin": ("中央政策", "中国政府网"),
    "/thepaper/featured": ("中央政策", "澎湃新闻"),
    "/zaobao/realtime/china": ("中央政策", "联合早报"),
    "/cls/telegraph": ("财经快讯", "财联社"),
    "/wallstreetcn/live": ("财经快讯", "华尔街见闻"),
    "/jin10": ("财经快讯", "金十数据"),
    "/yicai/brief": ("财经快讯", "第一财经"),
    "/36kr/newsflashes": ("科技新闻", "36氪"),
    "/ithome/ranking/24h": ("科技新闻", "IT之家"),
    "/huxiu/article": ("科技新闻", "虎嗅"),
    "/sspai/index": ("科技新闻", "少数派"),
}

# 默认启用的订阅路由列表（与 Dify 原型工作流一致，也可通过环境变量 DAILY_NEWS_ROUTES 覆盖）
DEFAULT_ACTIVE_ROUTES: list[str] = [
    "/thepaper/featured",       # 澎湃新闻
    "/cls/telegraph",           # 财联社
    "/wallstreetcn/live",       # 华尔街见闻
    "/yicai/brief",             # 第一财经
    "/36kr/newsflashes",        # 36氪
]


def get_active_routes() -> list[str]:
    """
    获取当前启用的 RSSHub 路由列表。
    支持通过环境变量 DAILY_NEWS_ROUTES（逗号分隔）动态增减源，无需改动代码。
    """
    custom = os.getenv("DAILY_NEWS_ROUTES", "").strip()
    if custom:
        return [r.strip() for r in custom.split(",") if r.strip()]
    return list(DEFAULT_ACTIVE_ROUTES)


def build_subscription_urls(rsshub_base_url: str, routes: list[str] | None = None) -> list[str]:
    """
    根据 RSSHub 基础地址与启用路由拼接完整的订阅 URL 列表。
    """
    base = rsshub_base_url.rstrip("/")
    target_routes = routes if routes is not None else get_active_routes()
    return [f"{base}{route}" for route in target_routes]


class TextParser(HTMLParser):
    """
    提取 HTML 片段中的纯文本，跳过 script/style 噪音并保留段落语义换行。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("p", "div", "br", "li", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("p", "div", "li"):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def clean_html(value: str) -> str:
    """
    将 RSS 描述中的 HTML 内容清洗为紧凑纯文本，去除多余空白行以节省送入 LLM 的 Token。
    """
    parser = TextParser()
    parser.feed(value or "")
    parser.close()
    lines = [
        re.sub(r"[ \t]+", " ", line).strip()
        for line in "".join(parser.parts).splitlines()
    ]
    return "\n".join(line for line in lines if line)


def read_date(value: str) -> str:
    """
    解析 RSS RFC822 pubDate 或 ISO 时间字符串，并统一转换为北京时间（+08:00）ISO 格式。
    边界条件：缺失时区信息时抛出 ValueError，避免不同时区时间混排导致最新新闻排序错乱。
    """
    try:
        dt = parsedate_to_datetime(value)
    except (ValueError, TypeError, OverflowError):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))

    if dt.tzinfo is None:
        raise ValueError("发布日期缺少时区")

    cn_tz = timezone(timedelta(hours=8))
    return dt.astimezone(cn_tz).isoformat()


def fetch_feed_with_retry(url: str, max_retries: int = 3) -> tuple[str, int]:
    """
    请求单个 RSSHub 订阅源，携带 filter_time=86400 仅拉取最近 24 小时内容，失败时最多重试 3 次。
    输出：(响应文本或错误详情, HTTP 状态码；网络异常时状态码为 0)。
    """
    last_err = ""
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(
                url,
                params={"filter_time": 86400},
                timeout=(10, 60),
            )
            return resp.text, resp.status_code
        except requests.RequestException as exc:
            last_err = str(exc)
            if attempt < max_retries:
                time.sleep(0.5 * attempt)
    return last_err, 0


def parse_single_feed(body: str, status_code: int, url: str) -> dict:
    """
    解析单个 RSS 2.0 XML 响应，每个源保留最新 6 条有效文章（正文截取前 1500 字），并记录采集诊断信息。
    """
    path = urlsplit(url).path.rstrip("/")
    category, source = SOURCES.get(path, ("未分类", path))

    report: dict = {
        "来源": source,
        "栏目": category,
        "订阅地址": url,
        "状态": "成功",
        "返回条数": 0,
        "日期缺失条数": 0,
        "有效条数": 0,
        "传出条数": 0,
        "文章": [],
    }

    try:
        if status_code != 200:
            err_msg = f"HTTP {status_code}: {body[:120]}" if status_code == 0 else f"HTTP {status_code}"
            raise ValueError(err_msg)

        # 清理可能存在的 UTF-8 BOM 头与前置空白，防止 ElementTree 解析报错
        root = ET.fromstring((body or "").lstrip("\ufeff \r\n\t"))
        channel = root.find("channel")
        if channel is None:
            raise ValueError("响应不是合法的 RSS 2.0 XML")

        items = channel.findall("item")
        report["返回条数"] = len(items)
        seen: set[str] = set()

        for item in items:
            title = clean_html(item.findtext("title") or "")
            link = (item.findtext("link") or "").strip()

            if not title or not link.startswith(("https://", "http://")) or link in seen:
                continue

            try:
                published = read_date((item.findtext("pubDate") or "").strip())
            except (ValueError, TypeError, OverflowError):
                report["日期缺失条数"] += 1
                continue

            seen.add(link)
            body_text = clean_html(
                item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
                or item.findtext("description")
                or ""
            )

            report["文章"].append({
                "栏目": category,
                "来源": source,
                "标题": title,
                "链接": link,
                "发布时间": published,
                "正文状态": "有订阅内容" if body_text else "正文未获取",
                "内容范围": "订阅内容前1500字符" if len(body_text) > 1500 else "订阅提供的内容",
                "正文": body_text[:1500],
            })

        report["文章"].sort(key=lambda article: article["发布时间"], reverse=True)
        report["有效条数"] = len(report["文章"])
        # 单源最多保留最新 6 条，避免单一高频快讯源挤占整栏配额
        report["文章"] = report["文章"][:6]
        report["传出条数"] = len(report["文章"])

        if not items:
            report["状态"] = "订阅为空"

    except (ValueError, ET.ParseError) as exc:
        report["状态"] = "读取失败"
        report["错误"] = str(exc)

    return report


def collect_all_feeds(urls: list[str], max_workers: int = 5) -> list[dict]:
    """
    并发拉取并解析所有订阅源，同时严格保持返回列表顺序与输入 urls 一致。
    """
    def _task(target_url: str) -> dict:
        body, status = fetch_feed_with_retry(target_url)
        return parse_single_feed(body, status, target_url)

    workers = max(1, min(max_workers, len(urls)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_task, urls))

    for rep in results:
        logger.info(
            "源采集结果 | %s (%s) | 状态=%s | 返回=%s | 有效=%s | 传出=%s%s",
            rep["来源"],
            rep["订阅地址"],
            rep["状态"],
            rep["返回条数"],
            rep["有效条数"],
            rep["传出条数"],
            f" | 错误={rep['错误']}" if "错误" in rep else "",
        )
    return results


def merge_feeds(results: list[dict], urls: list[str]) -> str:
    """
    合并所有订阅源解析结果，按三栏去重并按发布时间倒序排列（每栏最多保留最新 8 条、前 1000 字），
    连同采集覆盖情况序列化为紧凑 JSON 字符串交给 LLM 总结。
    """
    groups: dict[str, list[dict]] = {"中央政策": [], "财经快讯": [], "科技新闻": []}
    counts = dict.fromkeys(groups, 0)
    reports: list[dict] = []
    notices: list[str] = []
    seen_links: set[str] = set()
    received_urls: set[str] = set()
    expected_urls = set(urls)

    for index, report in enumerate(results):
        feed_url = report.get("订阅地址")
        if not isinstance(feed_url, str) or feed_url not in expected_urls:
            notices.append(f"第{index + 1}项订阅地址不在预期列表中，已跳过")
            continue
        if feed_url in received_urls:
            notices.append(f"订阅重复返回，已跳过：{feed_url}")
            continue
        received_urls.add(feed_url)

        reports.append({
            key: report[key]
            for key in ("来源", "订阅地址", "状态", "返回条数", "日期缺失条数", "有效条数", "传出条数", "错误")
            if key in report
        })

        for article in report.get("文章", []):
            category = article.get("栏目")
            link = article.get("链接", "")
            title = article.get("标题", "")
            if category not in groups or not title.strip() or not link.startswith(("https://", "http://")):
                continue

            # 剥离 URL 锚点后再去重，防止同一篇文章因 #hash 不同而重复入列
            key = link.split("#", 1)[0]
            if key in seen_links:
                continue
            seen_links.add(key)
            counts[category] += 1

            body = article.get("正文") or ""
            source = article.get("来源") or report.get("来源") or ""
            groups[category].append({
                "栏目": category,
                "来源": str(source)[:60],
                "标题": title[:200],
                "链接": link,
                "发布时间": str(article.get("发布时间") or ""),
                "正文状态": "有订阅内容" if body.strip() else "正文未获取",
                "内容范围": "订阅提供的内容，最多1000字符",
                "正文": body[:1000],
            })
            groups[category].sort(key=lambda item: item["发布时间"], reverse=True)
            del groups[category][8:]

    for url in dict.fromkeys(urls):
        if url not in received_urls:
            reports.append({"订阅地址": url, "状态": "未收到有效结果"})

    return json.dumps(
        {
            "时间范围": "最近24小时",
            "提示": notices,
            "采集情况": reports,
            "数量统计": {
                category: {"合并后条数": counts[category], "提交AI条数": len(groups[category])}
                for category in groups
            },
            "新闻": groups,
        },
        ensure_ascii=False,
    )
