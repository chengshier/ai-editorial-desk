# AI Editorial Desk

AI 编辑部系统：面向短视频创作者的多来源信息发现、资料整理、编辑判断与内容生产辅助系统。

**M1 已完成；M2-A 已完成并已合并；M2-B 已完成开发与 CI 验收，当前等待 PR #8 合并；M2-C / M2-D 未开始，M2 整体尚未完成。** 开发入口见 [`docs/START_HERE.md`](docs/START_HERE.md)，M1 验收证据见 [`docs/M1_ACCEPTANCE_REPORT.md`](docs/M1_ACCEPTANCE_REPORT.md)，MediaCrawler 本地边界见 [`docs/MEDIACRAWLER_LOCAL_CHANGES.md`](docs/MEDIACRAWLER_LOCAL_CHANGES.md)。

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
→ Checkpoint
→ Run 日志 / stale 检查 / 人工 retry
→ Validation 人工真实验收记录
```

M2-A 为 MediaCrawler 七个平台建立了共同的 **implementation adapter available** 基础状态；M2-B 在此基础上补齐七平台独立 Mapper、真实 capabilities/config_schema/ui_schema、统一评论模型与 `raw_signal_comments` 幂等持久化。评论继续受现有 Budget 控制。Fixture / Mock CI 只证明工程实现，不会把任何平台自动标记为真实 validated PASSED。

## M2-A MediaCrawler 集成

```text
CollectionTask
→ CollectorRuntime
→ MediaCrawlerConnector
→ MediaCrawlerAdapter
→ MediaCrawlerSubprocessRunner
→ third_party/MediaCrawler
→ 受控 JSONL / Result Envelope
→ CollectionResult / RawSignal
```

主要规则：

- 继续使用现有 `CollectorRuntime`、Run、Budget、Risk Guard、Checkpoint 和 RawSignal；
- `MediaCrawlerConnector` 注册到现有 Implementation Registry，不建立第二套 Registry；
- `MediaCrawlerInvocation` / `MediaCrawlerResultEnvelope` 使用版本化 Pydantic 协议；
- stdout/stderr 只作为有大小限制的诊断，不作为业务数据协议；
- 每个 Run 使用主系统创建的独立临时目录，限制结果大小并校验 JSON、协议版本、Run/Platform 身份；
- Adapter 不持有 ORM / AsyncSession，不自行提交数据库事务；
- `connector_checkpoints` 仍是权威，Result 只能返回 checkpoint candidate，最终由 Runtime 在成功入库后推进；
- 403 / 406 / 429 / CAPTCHA / 登录失效 / 账号受限或异常 / 自动化检测等风险候选进入现有 Risk Guard，不走普通 retry；
- subprocess 不继承 `DATABASE_URL`、Admin Token 或凭据环境；
- M2-A 显式关闭 MediaCrawler 代理开关，不实现代理轮换、验证码破解、指纹伪造、自动换号或绕过平台限制；
- M2-A 全部测试使用 Fixture / Fake subprocess / Mock，不连接真实平台、不登录、不扫码、不使用真实 Cookie。

## M2-B 七平台映射与评论标准化

M2-B 当前已完成开发与 CI 验收，等待 PR #8 合并。主要新增：

- MediaCrawler 七平台独立 Mapper 与显式 Platform Mapper Registry；
- 七平台真实能力对应的 `capabilities`、`config_schema`、`ui_schema`；
- 统一 `CollectedComment` Domain Model；
- PostgreSQL `raw_signal_comments` 与数据库唯一幂等约束；
- 评论幂等规则与评论 Budget 预留/结算；
- Result Envelope → Platform Mapper → RawSignal / CollectedComment 正式转换链；
- Web 继续使用现有动态 SchemaForm，不为七个平台手写独立页面。

当前能力声明保持保守：微博、B站、抖音、快手、贴吧开放 search/detail/creator/comments；知乎开放 search/detail/comments，creator 当前有效能力为 false；小红书当前仅开放 search，并允许 search 附带 comments；七平台 homefeed/hotlist 均未开放。

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

**M2-A / M2-B 均未更新上游版本，也未修改 vendored MediaCrawler 业务源码。** 主系统集成逻辑全部放在 `packages/connectors/mediacrawler_adapter/` 等主系统目录。详细记录见 `docs/MEDIACRAWLER_LOCAL_CHANGES.md`。

## 主要结构

```text
apps/api/                              FastAPI、健康检查和内部管理 API
apps/scheduler/                        asyncio + PostgreSQL 持久化 Scheduler
apps/web/                              React + Vite + TypeScript 内部连接器工作台
packages/connectors/                   Connector SDK 与现有真实实现
packages/connectors/mediacrawler_adapter/
                                      MediaCrawler 协议、Adapter、Runner、Connector、七平台 Mapper
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

M2-B 已完成开发与 CI 验收，但 PR #8 尚未合并；**M2 整体尚未完成**。下一步必须在 PR #8 合并后才进入 M2-C。

当前仍未实现或未开始：

- vendored Checkpoint / Incremental / Account Profile / SignatureProvider 增强；
- HomeFeed / 热榜真实发现；
- 微博、B站、知乎、抖音、小红书、快手、贴吧真实低量验证；
- Event / EventSignal；
- Embedding；
- 去重 / 聚类；
- AI Gateway / AI Provider / AI 评分 / 稿件生成。

这些属于 M2-C / M2-D 或后续阶段；PR #8 合并前不进入下一子阶段。
