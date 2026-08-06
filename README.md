# AI Editorial Desk

AI 编辑部系统：面向短视频创作者的多平台事件发现、资料整理、编辑判断与内容生产辅助系统。

项目当前已完成 **M1-B：连接器配置管理、运行记录与检查点服务**。完整产品路线和当前开发入口见 [`docs/START_HERE.md`](docs/START_HERE.md)。

## 当前结构

```text
apps/api/                         FastAPI 主服务、健康检查和内部管理 API
packages/database/                SQLAlchemy 2.x AsyncIO、Session、类型和 ORM 模型
packages/connectors/              Connector SDK、代码 Definition Manifest 和 MediaCrawler Adapter
packages/connector_management/    Repository、Service、Schema 校验、状态机和审计逻辑
packages/risk_guard/              平台账号状态、错误分类和风险动作
migrations/                       异步 Alembic 环境与版本迁移
scripts/                          连接器定义同步等内部维护命令
docker/postgres/                  PostgreSQL 扩展初始化
docs/                             PRD、技术文档、实施规划和进度记录
third_party/MediaCrawler/          Git Subtree 引入的完整第三方源码
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

定义同步命令可以重复运行。代码通过 `connector_type + platform` 定位 Definition，只更新代码拥有的名称、能力、Schema 和实现版本，不覆盖运营人员调整的 `is_enabled`。

## 健康与管理接口

- `GET /health`：只检查 API 进程存活；
- `GET /ready`：在限定超时内检查 PostgreSQL；
- `/api/v1/admin/*`：内部管理接口，必须携带 `X-Admin-Token`；
- 修改接口还必须携带 `X-Actor-ID`，用于 `updated_by` 和审计记录。

该 Token 仅是 M1-B 的最小内部保护，不是完整用户认证或 RBAC。

主要管理资源：

```text
/api/v1/admin/connector-definitions
/api/v1/admin/connector-instances
/api/v1/admin/platform-accounts
/api/v1/admin/connector-runs
/api/v1/admin/platform-risk-events
```

## M1-B 数据与安全规则

- Connector Definition 由代码 Manifest 管理，并通过 Draft 2020-12 JSON Schema 驱动配置；
- 普通 `config` 和 `schedule_config` 递归拒绝 Cookie、Token、API Key、密码、Session 和 Credential 等敏感字段；
- 凭据只保存 `credential_ref` / `browser_profile_ref`，管理响应不返回引用原值；
- Connector Instance 的实际配置变化才递增 `config_version`；
- 实例、账号和风险事件修改与 `configuration_change_logs` 在同一事务提交；
- 审计前后数据和 Run metadata 使用递归脱敏 JSONB；
- Platform Account 状态复用 Risk Guard `AccountStatus`，受限或停用账号不能直接恢复健康；
- Connector Run 终态不可继续修改；
- Checkpoint 使用 `expected_version` 和数据库原子条件执行乐观更新；
- Checkpoint 继续独立于 MediaCrawler 内部数据库。

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

# 条件允许时执行完整往返
alembic downgrade base
alembic upgrade head
```

CI 使用 PostgreSQL 16 + pgvector，不使用 SQLite 替代生产模型。根项目 Ruff 和 mypy 不检查 `third_party/MediaCrawler` 上游源码。

## M1-B 边界

本批次不执行真实 MediaCrawler 子进程，不包含 Scheduler、Worker、前端配置中心、完整凭据加密、完整认证/RBAC、配置快照回滚、Signal、Event、聚类、Embedding、AI Provider 或稿件生成，也不修改 MediaCrawler 平台业务源码和上游导入记录。
