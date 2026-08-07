# AI Editorial Desk

AI 编辑部系统：面向短视频创作者的多来源信息发现、资料整理、编辑判断与内容生产辅助系统。

**M1-A、M1-B、M1-C、M1-D 已完成开发与 CI 验收；M1 当前等待 PR #6 合并。PR 合并后进入 M2。** 完整路线、验收矩阵与开发入口见 [`docs/START_HERE.md`](docs/START_HERE.md) 和 [`docs/M1_ACCEPTANCE_REPORT.md`](docs/M1_ACCEPTANCE_REPORT.md)。

## M1 已建立的采集闭环

```text
代码 Definition + JSON Schema / UI Schema
→ Web 管理 Instance / Source / Schedule
→ PostgreSQL 持久化调度 + Lease + 时间槽防重复
→ CollectionTask
→ Collector Runtime
→ Budget + Risk Guard + Run 原子领取
→ RSS / Manual URL / 百度实时热榜
→ Raw Signal 标准化与 PostgreSQL 幂等写入
→ Checkpoint
→ Run 日志 / stale 检查 / 人工 retry
→ Validation 人工真实验收记录
```

M1 当前真实可运行实现为 `rss`、`manual` 和 `hotlist`。MediaCrawler 七个平台与 Reddit 仍只保留 Definition/后续接入边界，不宣称已经真实运行或 validated。

## 主要结构

```text
apps/api/                         FastAPI、健康检查和内部管理 API
apps/scheduler/                   asyncio + PostgreSQL 持久化 Scheduler
apps/web/                         React + Vite + TypeScript 内部连接器工作台
packages/connectors/              Connector 协议、RSS、Manual、Hotlist、安全 HTTP 边界
packages/connector_management/    Definition、Instance、Account、Run、Checkpoint 和审计
packages/collector_runtime/       预检、预算、原子领取、风险与受控运行时
packages/scheduling/              Schedule、Lease、stale/retry、Checkpoint 调试、Validation
packages/signals/                 URL、幂等、Source 和 Raw Signal 入库
packages/database/                Async SQLAlchemy、PostgreSQL 类型与 ORM
packages/risk_guard/              账号状态、风险分类和人工处置
migrations/                       独立可往返 Alembic migrations
third_party/MediaCrawler/          第三方源码；M1-D 不执行七个平台真实采集
```

## 本地启动

要求：Python 3.11—3.13、Node.js 22、Docker Desktop。

```bash
cp .env.example .env
# 修改 POSTGRES_PASSWORD、DATABASE_URL、APP_SECRET_KEY 和 APP_ADMIN_TOKEN

docker compose up -d postgres
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

alembic upgrade head
python -m scripts.sync_connector_definitions
uvicorn apps.api.main:app --reload
```

Scheduler 独立进程仍只负责触发现有 Runtime：

```bash
python -m apps.scheduler.main
```

Web：

```bash
cd apps/web
npm install
npm run dev
```

Web 的 API Base URL 使用环境配置；Admin Token 不硬编码进仓库，内部 MVP 仅在当前会话范围使用。写操作通过 `X-Actor-ID` 标识操作者。

## 内部管理能力

所有 `/api/v1/admin/*` 请求继续使用 `X-Admin-Token`，修改接口要求 `X-Actor-ID`。这是内部管理 MVP，不是完整用户认证/RBAC。

主要能力包括：

- Connector Definitions / Instances；
- Sources / Raw Signals；
- Collection Budgets；
- Schedules、pause/resume/run-now 与 Scheduler status；
- Connector Runs、详情、stale、retry、cancel；
- Checkpoints 查询与高风险 expected_version reset；
- Platform Accounts / Risk Events；
- Connector Validation 记录；
- Manual Import 和 Connector Test Run。

## M1 核心规则

- Connector 输出领域 RawSignal，不直接创建 ORM、不提交事务、不执行 AI；
- Raw Signal 使用稳定 v1 幂等键与 PostgreSQL unique + `ON CONFLICT DO NOTHING RETURNING`；
- Scheduler 的持久化状态、Lease 和时间槽唯一性全部落在 PostgreSQL，不以进程内 mutex 作为最终保证；
- Scheduler 只生成 CollectionTask 并调用 Collector Runtime，不绕过 Budget、Risk Guard、Run、Checkpoint 或幂等；
- stale RUNNING Run 只被识别，不自动无限重跑；人工 retry 创建新 Run 并保留 parent_run_id；
- Checkpoint 仅在信号提交后推进；高风险 reset 使用 expected_version、Actor、reason 和审计，且不删除 Raw Signal；
- RSS、Manual URL 与 Hotlist 共享安全网络边界；拒绝 localhost、私网、链路本地、云元数据地址及危险 Redirect；
- 百度实时热榜只做低频、小条数公开读取，不使用登录、Cookie、验证码、签名破解或代理轮换；
- Definition 的 registered、implemented、enabled、validated 彼此独立；
- CI fixture/mock 不会自动把 Connector 标记为 validated；PASSED 记录要求人工操作、非 CI/Mock 环境和同 Definition 的 SUCCEEDED Test/Manual Run ID；
- API、日志、Run metadata、Raw payload 与 Web 不展示 Cookie、Token、Authorization、API Key、credential_ref/browser_profile_ref 原值。

## 最终 M1 验证

GitHub Actions 在 PostgreSQL 16 + pgvector 中通过：

```bash
ruff check .
mypy apps packages
pytest
alembic upgrade head
alembic downgrade -1
alembic upgrade head
alembic downgrade base
alembic upgrade head
python -m scripts.sync_connector_definitions
python -m scripts.sync_connector_definitions
```

最终 Python：**120 passed**。Web：

```bash
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

最终 Web：**6 个 test files、8 tests passed，production build 成功**。

详细逐项证据见 [`docs/M1_ACCEPTANCE_REPORT.md`](docs/M1_ACCEPTANCE_REPORT.md)。

## 当前边界与下一阶段

M1 没有实现 Event/EventSignal、Embedding、pgvector 相似检索、事件聚类、AI Gateway、AI Provider、AI 评分、证据提取或稿件生成，也没有执行 MediaCrawler 七个平台真实采集或引入 Redis/Celery。

**PR #6 合并后进入 M2；不要直接跳入 M3 的 Event / Embedding / 聚类范围。**
