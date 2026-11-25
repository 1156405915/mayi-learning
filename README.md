# 🤖 agent-learning

个人 AI Agent 工程化学习与实战仓库：将验证过的 Agent 工作流沉淀为**模块化 Python 代码**，通过**单个 Docker 容器统一调度管理**，并在 `docs/` 中配套维护每个 Agent 的**架构方案与排障复盘文档**。

---

## 📂 目录结构

```text
agent-learning/
├── .env.example                 # 环境变量配置模板（复制为 .env 使用）
├── Dockerfile                   # 多 Agent 统一运行镜像
├── docker-compose.yml           # 容器编排配置（代码与定时配置热挂载）
├── requirements.txt             # Python 依赖清单
├── schedules.yaml               # 声明式定时调度表（Cron）
├── main.py                      # 统一 CLI 入口（list / run / serve）
│
├── core/                        # 公共基础设施层（供所有 Agent 复用）
│   ├── config.py                # .env 自动加载、全局配置与标准日志
│   ├── llm.py                   # OpenAI / DeepSeek 兼容接口封装（含重试与用量日志）
│   └── notify/
│       └── feishu.py            # 飞书自建应用消息 & 群机器人 Webhook 推送
│
├── agents/                      # 独立的 Agent 业务实现
│   ├── registry.py              # Agent 注册中心
│   └── daily_news/              # [01] 每日新闻简报 Agent
│       ├── agent.py             # 四步主流程编排
│       ├── collector.py         # RSSHub 并发采集、XML/HTML 清洗与三栏去重
│       └── prompts.py           # 编辑规范 System Prompt 模板
│
└── docs/                        # Docsify 在线文档站（架构方案与学习笔记）
    ├── index.html               # Docsify 入口（支持侧边栏、全文搜索、Mermaid 图表）
    ├── _sidebar.md              # 文档导航目录
    ├── architecture.md          # 多 Agent 容器化底座与扩展指南
    ├── agents/
    │   └── 01-daily-news.md     # 每日新闻简报 Agent 架构与实现详解
    └── infra/
        └── rsshub-searxng.md    # RSSHub / SearXNG 部署与 Docker 内网隔离实战
```

---

## 🚀 快速开始

### 1. 本地开发与调试

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 初始化环境变量配置
cp .env.example .env
# 编辑 .env 填入 LLM_API_KEY 与飞书凭证

# 3. 查看已注册的所有 Agent
python main.py list

# 4. 分阶段调试每日新闻简报 Agent
python main.py run daily_news --collect-only   # 仅测试 RSSHub 采集与去重（不调 LLM、不推飞书）
python main.py run daily_news --dry-run        # 生成简报并在终端预览（跳过飞书推送）
python main.py run daily_news                  # 完整执行并推送飞书
```

### 2. Docker 容器化部署（服务器推荐）

```bash
# 在服务器上配置好 .env（容器内 RSSHUB_BASE_URL 默认走 http://rsshub:1200）
sudo docker compose up -d --build

# 查看实时调度与运行日志
sudo docker logs --tail 100 -f agents-runner

# 随时在容器内手动触发一次指定 Agent
sudo docker exec agents-runner python main.py run daily_news
```

### 3. 在线阅读 `docs` 架构与学习文档

```bash
python -m http.server 3000 -d docs
```

浏览器打开 `http://127.0.0.1:3000` 即可阅读全部架构图解与复盘文档（也可在 GitHub 仓库 Settings -> Pages 中将 Source 设为 `main` 分支 `/docs` 目录直接发布在线站点）。

---

## ➕ 如何新增一个 Agent？

1. 在 `agents/<new_agent>/` 下编写业务逻辑（直接调用 `core.llm.LLMClient` 与 `core.notify.feishu.FeishuNotifier`）；
2. 在 `agents/registry.py` 注册一条 `AgentSpec`；
3. 在 `schedules.yaml` 添加 Cron 时间，并在 `docs/agents/` 补充架构说明文档。

详细模板请参考 [docs/architecture.md](docs/architecture.md)。
