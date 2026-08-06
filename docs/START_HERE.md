# AI 编辑部项目开发入口

## 当前阶段

项目已完成 **M1-A：异步数据库底座与第一批核心数据模型**，下一步建议进入 M1-B。

## 必读文档顺序

1. `DECISIONS.md`
2. `AI编辑部_综合开发实施规划_V1.2.md`
3. `AI编辑部_技术开发文档_V1.2.md`
4. `AI编辑部_PRD_V1.2.md`
5. `CHANGELOG.md`

如文档存在冲突，优先级为：

1. `DECISIONS.md`
2. 综合开发实施规划
3. 技术开发文档
4. PRD

## 已确认决策摘要

- 主仓库为 `ai-editorial-desk`；
- MediaCrawler 作为 `third_party/MediaCrawler` 内置第三方采集模块；
- MVP 通过 Adapter + 子进程调用 MediaCrawler，不要求单独启动 HTTP 服务；
- PostgreSQL + pgvector 通过 Docker Desktop 运行；
- MVP 默认使用云 Embedding，同时保留本地 Provider 接口；
- 平台连接器、AI Provider、模型路由和调度采用可视化配置；
- MediaCrawler 只吸收五项：断点续采、增量采集、账号/Profile 抽象、签名解耦、有限 HomeFeed 与热榜能力；
- 必须实现平台账号风险保护、预算、熔断和人工恢复；
- 不实现验证码破解、指纹伪造、封禁后自动换号或绕过平台限制。

## 已完成基线

- 主仓库和 Python 3.11+ 工程骨架；
- PostgreSQL + pgvector Docker Compose；
- FastAPI `/health` 与数据库 `/ready`；
- Connector SDK、注册中心、MediaCrawler 子进程 Adapter；
- MediaCrawler 完整源码通过 Git Subtree 引入 `third_party/MediaCrawler`；
- Risk Guard 账号状态和保守错误分类；
- SQLAlchemy 2.x 异步 Engine、Session、FastAPI 依赖和统一 Declarative Base；
- UUID、UTC、JSONB、字符串枚举和数据库异常规范；
- 异步 Alembic 环境和首份可往返迁移；
- `connector_definitions`、`connector_instances`、`platform_accounts`、`connector_runs`、`connector_checkpoints`、`platform_risk_events` 六组表；
- PostgreSQL Service Container CI、Ruff、mypy、pytest 和迁移往返验证。

## M1-A 明确边界

本批仅建立持久化底座和核心模型，不包含：

- Connector CRUD API 和可视化页面；
- Scheduler、Worker、队列和真实采集；
- MediaCrawler 平台业务源码修改及五项增强；
- 完整凭据加密系统、自动账号恢复、自动换号或代理轮换；
- Signal、事件、聚类、Embedding、AI Provider 和稿件生成。

## 下一步 M1-B 建议

1. Connector Definition 初始化与版本策略；
2. Connector Instance 服务层和 CRUD API；
3. 配置 Schema 校验、敏感字段拆分接口；
4. 账号与风险事件查询/人工状态变更服务；
5. 运行记录和 checkpoint Repository；
6. API 测试、权限边界与审计字段补全。

## 开发原则

- 每次只开发一个可验收模块；
- 不擅自扩大当前迭代范围；
- 不把事件聚类、AI 评分、稿件和前端业务写入 MediaCrawler；
- 新增运营配置优先考虑后台可视化；
- 密钥只能进入环境变量或独立凭据存储；
- 风控信号不进入普通重试循环。
