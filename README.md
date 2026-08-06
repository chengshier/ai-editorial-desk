# AI Editorial Desk

AI 编辑部系统：面向短视频创作者的多平台事件发现、资料整理、编辑判断与内容生产辅助系统。

项目当前已完成 **M1-A：异步数据库底座与第一批核心数据模型**。完整产品路线和当前开发入口见 [`docs/START_HERE.md`](docs/START_HERE.md)。

## 当前结构

```text
apps/api/                         FastAPI 主服务与健康检查
packages/database/                SQLAlchemy 2.x AsyncIO、Session、类型和 ORM 模型
packages/connectors/              统一 Connector SDK 与 MediaCrawler Adapter
packages/risk_guard/              平台账号状态、错误分类和风险动作
migrations/                       异步 Alembic 环境与版本迁移
docker/postgres/                  PostgreSQL 扩展初始化
docs/                             PRD、技术文档、实施规划和进度记录
third_party/MediaCrawler/          Git Subtree 引入的完整第三方源码
```

## 本地启动

要求：Python 3.11—3.13、Docker Desktop。

```bash
cp .env.example .env
# 修改 .env 中的 POSTGRES_PASSWORD、DATABASE_URL 和 APP_SECRET_KEY

docker compose up -d postgres

python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

alembic upgrade head
uvicorn apps.api.main:app --reload
```

健康检查：

- `GET /health`：只检查 API 进程存活；
- `GET /ready`：在限定超时内执行 PostgreSQL `SELECT 1`，数据库不可用时返回 503，且不暴露连接凭据。

## 数据库规范

- PostgreSQL + pgvector，本地推荐端口 `55432`；
- SQLAlchemy 2.x AsyncIO + `asyncpg`；
- UUID v4 主键；
- 时间字段必须带时区并统一归一化为 UTC；
- 动态配置、Schema、checkpoint 和必要风险上下文使用 PostgreSQL JSONB；
- Cookie、Token、API Key 不进入普通配置或风险日志，只保存凭据引用；
- 主系统 checkpoint 和 ORM 不依赖 MediaCrawler 内部数据库结构。

## 验证

```bash
ruff check .
mypy apps packages
pytest
alembic upgrade head
alembic downgrade base
alembic upgrade head
```

根项目 Ruff 和 mypy 不检查 `third_party/MediaCrawler` 上游源码。

## M1-A 边界

本批次不包含 Connector CRUD API、Scheduler、Worker、前端配置页、MediaCrawler 五项增强、完整凭据加密、事件聚类、Embedding、AI Provider 或稿件生成。下一批 M1-B 建议从数据库服务层、Connector Definition 初始化与 CRUD API 开始。
