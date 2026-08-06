# AI Editorial Desk

AI 编辑部系统：面向短视频创作者的多来源事件发现、资料整理、编辑判断与内容生产辅助系统。

项目当前进入 **M1-C：原始信号、真实基础连接器与受控采集运行时**。完整产品路线和当前开发入口见 [`docs/START_HERE.md`](docs/START_HERE.md)。

## 当前能力

```text
代码 Definition
→ 实例与 Source 配置
→ 账号状态、Risk Guard 与数据库预算预检
→ PENDING Run 原子领取
→ RSS / 手工 URL 有界采集
→ Raw Signal 标准化与幂等写入
→ 已提交信号后推进 Checkpoint
→ Run 终态、风险与审计记录
```

M1-C 只将 `rss` 和 `manual` 注册为真实可运行实现。MediaCrawler 七个平台、Reddit 和热榜仍只是 Definition，不会被标记为 implemented 或 validated。

## 主要结构

```text
apps/api/                         FastAPI、健康检查和内部管理 API
packages/connectors/              Connector 领域协议、RSS、手工 URL、安全 HTTP 边界
packages/connector_management/    Definition、实例、账号、Run、Checkpoint 和审计
packages/collector_runtime/       任务协议、预检、预算、原子领取、风险和运行时编排
packages/signals/                 URL、幂等规则、Source 和 Raw Signal 入库服务
packages/database/                Async SQLAlchemy、类型与 ORM
packages/risk_guard/              账号状态、风险分类和人工处置
migrations/                       独立可往返 Alembic migration
third_party/MediaCrawler/          Git Subtree 第三方源码，本批不修改平台业务代码
```

## 本地启动

要求：Python 3.11—3.13、Docker Desktop。

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

## 内部管理接口

所有 `/api/v1/admin/*` 请求需要 `X-Admin-Token`，修改接口还需要 `X-Actor-ID`。

```text
/api/v1/admin/connector-definitions
/api/v1/admin/connector-instances
/api/v1/admin/platform-accounts
/api/v1/admin/sources
/api/v1/admin/raw-signals
/api/v1/admin/collection-budgets
/api/v1/admin/connector-runs
/api/v1/admin/platform-risk-events
POST /api/v1/admin/connector-instances/{id}/test-runs
POST /api/v1/admin/manual-imports
```

该 Token 是内部开发阶段的最小保护，不是完整认证或 RBAC。

## M1-C 核心规则

- `sources` 表示实例下的具体采集范围；归档只停用，不删除历史信号；
- Connector 输出独立领域模型，不创建 ORM、不提交事务、不调用 AI；
- URL 只接受 HTTP/HTTPS，统一规范化 scheme、host、默认端口、fragment 和有限跟踪参数；
- 幂等键规则版本为 `v1`：优先 external ID，其次 canonical URL，最后来源、内容哈希与发布时间；
- Raw Signal 使用 PostgreSQL `ON CONFLICT DO NOTHING RETURNING`，并发重复只能创建一条；
- RSS 支持 RSS 2.0、Atom、ETag、Last-Modified、304、超时、响应体与 Content-Type 限制；
- 手工 URL 每次 DNS 解析和每一跳重定向都验证地址，拒绝本机、私网、链路本地、多播、保留和云元数据地址；
- Run 领取和终态采用带旧状态条件的数据库原子更新；
- 预算使用数据库行锁与自然日 usage 记录，不依赖进程内计数；
- 网络请求不持有长数据库事务；每批信号成功提交后才允许推进 Checkpoint；
- 普通 RSS/HTTP 错误不会被误标记为账号封禁；真实平台风险可进入 `PAUSED_RISK` 和人工复核；
- API、日志、Run metadata、风险上下文和 Raw payload 不返回或持久化明文凭据。

## 验证

```bash
ruff check .
mypy apps packages
pytest
alembic upgrade head
alembic downgrade -1
alembic upgrade head
python -m scripts.sync_connector_definitions
python -m scripts.sync_connector_definitions
alembic downgrade base
alembic upgrade head
```

CI 使用 PostgreSQL 16 + pgvector。RSS 和手工 URL 测试只使用 Fixture、MockTransport 或不抓取模式，不依赖真实互联网。

## 当前边界

M1-C 不包含 Scheduler、Worker、Celery、Redis 队列、前端配置页面、MediaCrawler 子进程、平台实跑、评论采集、浏览器登录、事件聚类、Embedding、AI Provider、AI 评分、证据提取或稿件生成。下一阶段应进入 **M1-D**，而不是直接进入 M2。
