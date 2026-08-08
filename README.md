# AI Editorial Desk

AI 编辑部系统：面向短视频创作者的多来源信息发现、资料整理、编辑判断与内容生产辅助系统。

**M1 已完成；M2 Engineering Complete；M2 Real Smoke Validation = DEFERRED / NOT_TESTED。** M2 工程完成不等于真实平台验证完成。PR #10 合并后允许从最新 `main` 独立进入 M3 Engineering；当前 M3 尚未开始。开发入口见 [`docs/START_HERE.md`](docs/START_HERE.md)，M2 验收状态见 [`docs/M2_ACCEPTANCE_REPORT.md`](docs/M2_ACCEPTANCE_REPORT.md)，真实 Smoke 环境指南见 [`docs/M2_REAL_SMOKE_SETUP.md`](docs/M2_REAL_SMOKE_SETUP.md)。

## 当前采集闭环

```text
代码 Definition + JSON Schema / UI Schema
→ Web 管理 Instance / Source / Schedule
→ PostgreSQL Scheduler / Lease / 时间槽防重复
→ CollectionTask
→ CollectorRuntime
→ Budget + Risk Guard + Run 原子领取
→ RSS / Manual URL / 百度实时热榜 / MediaCrawler Adapter
→ Platform Mapper
→ RawSignal / CollectedComment 标准化与 PostgreSQL 幂等写入
→ Checkpoint / Incremental / Resume
→ Run 日志 / stale 检查 / 人工 retry
→ Validation 人工真实验收记录
```

M2-A 建立 MediaCrawler 主系统 Adapter / Runtime 集成；M2-B 补齐七平台独立 Mapper、真实 capabilities/config_schema/ui_schema、统一评论模型与 `raw_signal_comments` 幂等持久化；M2-C 补齐 Checkpoint / Incremental / Resume、Account / Browser Profile、SignatureProvider 与风险信号边界；M2-D 完成离线 Smoke Harness、B站/知乎低量请求 compatibility、环境 preflight、login-only preflight 与真实 Smoke 操作指南。

Fixture / Mock / CI 只证明工程实现，**不会把任何平台自动标记为真实 validated PASSED**。

## M2-D 最终工程状态

| 项目 | 状态 |
|---|---|
| B站 low-volume Detail/Search engineering | READY |
| 知乎 low-volume Detail/Search engineering | READY |
| 微博 Detail engineering entry | READY（未实跑） |
| 微博 low-volume Search | BLOCKED / Accepted Known Limitation |
| B站 Real Smoke / Validation | NOT_TESTED |
| 知乎 Real Smoke / Validation | NOT_TESTED |
| 微博 Real Smoke / Validation | NOT_TESTED |
| M2 Engineering | COMPLETE |
| M2 Real-world Validation | NOT COMPLETE |

微博 pinned client 当前没有已经证实的 `page_size` / `count` / `limit` 能力，因此不猜 API 参数、不逆向接口、不扩展 Signature；该限制不再阻塞 M3 Engineering。未来只有 upstream 明确提供低量参数、新 pinned version 出现可验证实现，或有正规源码证据证明现有接口支持低量请求时，才重新打开微博 Search Gate。

## MediaCrawler 第三方边界

Vendored 路径：

```text
third_party/MediaCrawler/
```

固定上游 commit：

```text
071c8c0acaece3e82f2532cffb19faeddc9ec1c3
```

许可证：`NON-COMMERCIAL LEARNING LICENSE 1.1`。

M2-D 仅保留两处经过审计的最小 compatibility patch：

```text
third_party/MediaCrawler/media_platform/bilibili/core.py
third_party/MediaCrawler/media_platform/zhihu/core.py
```

两处都只降低 normal search 的真实 page-size/request-volume，不修改登录、Cookie、CDP、Signature、Risk Guard、代理、stealth、CAPTCHA 或账号逻辑。微博和其他平台没有新增 vendored patch。详细记录见 `docs/MEDIACRAWLER_LOCAL_CHANGES.md`。

## 主要结构

```text
apps/api/                              FastAPI、健康检查和内部管理 API
apps/scheduler/                        asyncio + PostgreSQL 持久化 Scheduler
apps/web/                              React + Vite + TypeScript 内部连接器工作台
packages/connectors/                   Connector SDK 与现有真实实现
packages/connectors/mediacrawler_adapter/
                                      MediaCrawler 协议、Adapter、Runner、Connector、七平台 Mapper、Smoke readiness
packages/connector_management/         Definition、Instance、Account、Run、Checkpoint、审计
packages/collector_runtime/            预检、Budget、Run、Risk 与受控 Runtime
packages/scheduling/                   Schedule、Lease、stale/retry、Checkpoint 调试、Validation
packages/signals/                      URL、幂等、Source、RawSignal 与评论入库
packages/database/                     Async SQLAlchemy、PostgreSQL 类型与 ORM
packages/risk_guard/                   账号状态、风险分类与人工处置
migrations/                            Alembic migrations
third_party/MediaCrawler/              固定上游第三方源码
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

Scheduler：

```bash
python -m apps.scheduler.main
```

Web：

```bash
cd apps/web
npm install
npm run dev
```

真实平台 Smoke 的双 venv、Chrome/Edge CDP 9222、Browser Profile、低价值测试 Account、极低 Budget 与 Validation 操作必须按 `docs/M2_REAL_SMOKE_SETUP.md` 执行；当前 Real Smoke 已正式 Deferred，不要求为进入 M3 Engineering 立即配置。

## CI 验收命令

Python / PostgreSQL：

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

Web：

```bash
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

`third_party/MediaCrawler` 继续排除在根 Ruff 之外。

## 当前阶段边界

M2 最终工程基线已通过 CI #177：Ruff success、mypy 128 source files、pytest 240 passed / 1 warning、Alembic 完整往返、Definition 第二次同步 `unchanged=11 / failed=0`，Web lint/typecheck/test/build 全部 success。

当前正式状态：

```text
M2 Engineering Complete
Real Smoke Validation Deferred / NOT_TESTED
M2 Real-world Validation NOT COMPLETE
M3 Engineering allowed after PR #10 merge
```

PR #10 合并后，下一步从**最新 `main`** 创建独立 M3-A 分支，不从 M2-D feature branch 继续派生。

M3 next：**Event / EventSignal → Embedding → Dedup → Clustering**。M4/M5 Engineering 后续也可以继续推进，但在 M5 宣布真实世界 / Production Validation 完成之前，必须至少补一次受控的真实端到端平台 Smoke；优先从 B站或知乎开始。

当前 M3 尚未开始，也没有任何真实平台 PASSED Validation。
