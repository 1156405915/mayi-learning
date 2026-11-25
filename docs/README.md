# Agent Learning 实战与架构知识库

本项目用于沉淀个人在 **AI Agent 设计、工程化代码落地与容器化运维** 过程中的实战项目与复盘笔记。

核心工作流遵循 **「低代码快速验证（Dify） ➔ Python 模块化重构 ➔ Docker 单容器多任务托管 ➔ Docsify 架构文档沉淀」** 的闭环演进路线。

---

## 模块地图

| 分类 | 内容 | 核心收获 |
|---|---|---|
| **架构底座** | [多 Agent 容器化底座架构](architecture.md) | 单容器 `agents-runner` 设计、`core/` 公共能力复用、`APScheduler` 声明式调度、3 步接入新 Agent |
| **Agent 01** | [每日新闻简报 Agent](agents/01-daily-news.md) | RSSHub 并发采集、HTML 清洗与时区归一化、三栏去重、防幻觉编辑提示词、采集覆盖率自检、飞书推送 |
| **基础设施** | [RSSHub & SearXNG 内网隔离实战](infra/rsshub-searxng.md) | 国内云主机搜索引擎诊断、Docker 自定义网络 DNS 机制、Dify `ssrf_proxy` 404 排障与服务网络解耦 |

---

## 本地快速体验

### 1. 环境准备

```bash
# 创建虚拟环境并安装依赖（可选）
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# Linux / macOS:      source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

### 2. 常用调试命令

```bash
# 查看当前项目中已注册的所有 Agent
python main.py list

# 仅测试 RSSHub 数据采集与清洗合并（无需配置大模型与飞书密钥）
python main.py run daily_news --collect-only

# 试运行：调用大模型生成简报并在终端打印，跳过飞书推送
python main.py run daily_news --dry-run

# 完整运行并推送到飞书群
python main.py run daily_news
```

### 3. 本地预览本文档站

```bash
python -m http.server 3000 -d docs
```

启动后在浏览器访问 `http://127.0.0.1:3000` 即可获得带侧边栏导航、全文检索与架构图渲染的阅读体验。
