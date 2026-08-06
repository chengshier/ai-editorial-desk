# 文档与架构变更记录

## 2026-08-06 — M1-A

- 建立 SQLAlchemy 2.x 异步 Engine、Session 生命周期和 FastAPI 数据库依赖；
- 建立统一 Declarative Base、UUID 主键、UTC 时间和 PostgreSQL JSONB 规范；
- 初始化异步 Alembic，并增加首份可 upgrade/downgrade 的迁移；
- 新增 connector definitions、instances、platform accounts、runs、checkpoints 和 platform risk events 六组模型；
- ORM 账号状态直接复用 Risk Guard `AccountStatus`，运行状态使用独立字符串枚举；
- 增加 checkpoint 范围唯一性、计数非负、外键和常用查询索引；
- 风险上下文写入前自动脱敏 Cookie、Token、Authorization、API Key 等字段；
- `/health` 保持纯存活检查，`/ready` 增加限时数据库检查和无凭据泄露的 503 响应；
- CI 增加 PostgreSQL Service Container、mypy、pytest 和 Alembic 往返验证；
- 更新 README 与开发入口，明确 M1-A 边界和 M1-B 建议。

## 2026-08-06 — M0 / 初始骨架

- 初始化 `ai-editorial-desk` 主仓库；
- 确认 MediaCrawler 作为 `third_party` 内置采集模块；
- 确认 MVP 采用 Adapter + 子进程调用方式；
- 加入 PostgreSQL + pgvector、FastAPI、Connector SDK 和风险保护骨架；
- 纳入 PRD、技术开发文档和综合开发实施规划 V1.2。
