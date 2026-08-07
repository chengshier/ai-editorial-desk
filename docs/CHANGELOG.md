# 文档与架构变更记录

## 2026-08-07 — M1-D 与 M1 最终收口

- 新增 PostgreSQL 持久化 `collection_schedules`、`collection_schedule_triggers`、`scheduler_instances` 与 `connector_validation_records`，并以独立 `20260807_0004_m1d_scheduler_workbench.py` migration 管理；
- 建立 asyncio + PostgreSQL Scheduler，使用数据库 Lease 与时间槽唯一约束防止多 Scheduler 重复触发，Scheduler 只生成 CollectionTask 并调用既有 Collector Runtime；
- 增加 Scheduler heartbeat、Lease 过期恢复和 stale 执行人工检查策略，不引入 Redis/Celery；
- 扩展 Run trigger、parent retry、retry_count、进度时间和调试信息，增加 stale Run 查询、人工失败/取消和 retry 新 Run；
- Retry 继续执行 Budget、Risk Guard、Checkpoint 与 RawSignal 幂等，不允许无限自动重试；
- 增加 Checkpoint 查询与 expected_version 高风险 reset，要求 Actor/reason、写审计，且 reset 不删除历史 Raw Signal；
- 实现 Hotlist 统一能力与百度实时热榜低风险公开入口，复用 SafeHTTPFetcher 的 SSRF、Redirect、超时、响应大小和 Content-Type 限制；
- 增加 Connector Validation NOT_TESTED/PASSED/FAILED/EXPIRED；PASSED 拒绝 CI/Mock 环境，并要求人工真实 Smoke 标记及同 Definition 的 SUCCEEDED Test/Manual Run ID；
- 建立 React + Vite + TypeScript 基础连接器工作台，包含 Definitions、Instances、Sources、Schedules、Runs、Checkpoints、Accounts/Risk 页面；
- JSON Schema / UI Schema 已用于动态配置表单；Instance/Source 支持新建、编辑、启停/归档和 Test Run，Instance 支持 Run Now；
- 修复 M1-D 初始 CI 中 Ruff、mypy、Vitest globals、SchemaForm required 优先级、React Hook dependency、迁移测试事件循环与 stale Run rollback 后 ORM 过期问题；
- 新增 PostgreSQL 集成测试验证 Scheduler lease 并发单赢家、Lease 过期恢复、时间槽唯一、heartbeat、Scheduler → Runtime 闭环、stale/retry、Budget/Risk Guard、Checkpoint 并发 reset、Validation 与 Hotlist Runtime 幂等；
- 最终 GitHub Actions 在 PostgreSQL 16 + pgvector 中通过 `ruff check .`、`mypy apps packages` 和 **120 项 pytest**；
- Alembic `upgrade head → downgrade -1 → upgrade head → downgrade base → upgrade head` 完整通过；
- Connector Definition 连续同步两次，第二次 `created=0 / updated=0 / unchanged=11 / failed=0`；
- Web `lint`、`typecheck`、**6 个 test files / 8 tests** 与 production build 全部通过；
- 新增 `docs/M1_ACCEPTANCE_REPORT.md`，逐项记录 M1 实现、测试、CI 状态与限制；
- M1 工程开发与 CI 验收完成；PR #6 仍保持 Open，等待人工代码审查与合并，未进入 M2、Event、Embedding、AI 或 MediaCrawler 七平台实跑。

## 2026-08-07 — M1-C PostgreSQL 验收收口

- 修复 `collection_budget_usage` migration 缺少 UUID 主键列、但已声明主键约束的问题，并增加主键回归测试；
- 将 Source 敏感配置拒绝统一映射为 400 业务错误，同时保留 M1-B Connector Schema 的 422 校验语义；
- 修正 M1-B migration 测试的起始版本，使其明确验证 `base → 0002 → 0001`，不依赖当前数据库已处于哪个 head；
- 手工 URL 连接器不再将 `UnsafeURLError` 包装为普通抓取失败，SSRF、私网和元数据地址风险直接中止；
- 修正 Risk Guard 运行测试在 `rollback()` 后访问过期 ORM 实例的问题，改为预先缓存不可变 UUID；
- GitHub Actions 最终执行完整 `pytest`，并按 `upgrade head → downgrade -1 → upgrade head → downgrade base → upgrade head` 顺序验证 Alembic；
- PostgreSQL 16 + pgvector 环境中 101 项测试通过，覆盖 Run 原子领取、预算并发预留、Raw Signal 幂等、SSRF 与 Risk Guard；
- 本次收口未降低唯一约束、锁、事务保护或安全测试标准，未接入 Scheduler/Worker、MediaCrawler、Event、Embedding、LLM 或 M1-D。

## 2026-08-06 — M1-C

- 新增 `sources`、`raw_signals`、`collection_budgets` 和 `collection_budget_usage` 四组正式模型；
- 新增独立 `20260806_0003_m1c_collector_runtime.py` migration，不修改 M1-A/M1-B migration；
- Connector 统一输出独立 RawSignal 领域模型，不直接创建 ORM 或提交事务；
- 新增 HTTP/HTTPS URL 规范化、有限跟踪参数移除、稳定 content hash 和 v1 幂等键；
- Raw Signal 使用 PostgreSQL `ON CONFLICT DO NOTHING RETURNING`，支持并发单条创建；
- 实现 RSS 2.0、Atom、ETag、Last-Modified、304、条目级错误和安全 Checkpoint；
- 实现手工 URL 导入、有限 HTML/文本提取、用户内容回退和内容来源标记；
- 新增逐跳 DNS/重定向 SSRF 防护、超时、响应体、Content-Type 和安全请求头限制；
- 新增显式 Implementation Registry，仅注册 RSS 与手工 URL 的真实实现；
- 新增可序列化 CollectionTask，预留 manual/test/scheduled/retry 触发类型；
- 将 Run 领取和终态转换改为带旧状态条件的数据库原子更新；
- 新增数据库预算规则、按时区自然日 usage、行锁预留和并发限制；
- 建立受控 Collector Runtime，网络调用不占用长事务，信号提交后才推进 Checkpoint；
- 接入 Risk Guard，真实平台风险可写事件并进入 `PAUSED_RISK`，普通 RSS/HTTP 错误不误判为封禁；
- 新增 Source、Raw Signal、Budget、test-run 和 manual-import 内部管理 API；
- Definition API 增加 registered、implemented、enabled、validated 计算状态；
- 新增 RSS、Atom、304、SSRF、重定向、超时、响应限制、幂等、预算和 Run 并发测试；
- 本批未接 Scheduler/Worker，未执行 MediaCrawler，未进入 Event、Embedding、LLM 或稿件生成。

## 2026-08-06 — M1-B

- 增加 11 个代码管理的 Connector Definition Manifest，覆盖 MediaCrawler 七个平台、RSS、Reddit、热榜和手工 URL；
- 增加幂等定义同步服务和 `python -m scripts.sync_connector_definitions` 命令；
- 同步使用 `connector_type + platform` 定位，只更新代码拥有字段并保留人工 `is_enabled`；
- 引入 JSON Schema Draft 2020-12，增加 Connector config 和公共 schedule config 校验；
- 普通配置递归拒绝 Cookie、Token、Authorization、API Key、密码、Session 和 Credential 等敏感字段；
- 增加 Definition、Instance、Platform Account、Run 和 Risk Event 的内部管理 API；
- 增加 Connector Instance 配置版本、启停、归档和事务审计；
- 增加 Platform Account 人工状态转换矩阵，不允许受限或停用账号直接恢复健康；
- 增加 Connector Run 状态服务、终态保护、计数更新和 metadata 脱敏；
- 增加 Checkpoint 原子 expected_version 乐观更新与并发冲突异常；
- 增加 Risk Event 查询和人工处理，处理事件不会自动恢复账号；
- 新增 `configuration_change_logs` 轻量审计表，并为平台账号补充 `updated_by`；
- 增加 `APP_ADMIN_TOKEN`、`X-Admin-Token` 和写操作 `X-Actor-ID` 最小内部保护；
- 增加 M1-B PostgreSQL 集成测试、独立 migration 往返和 Definition 双次同步 CI；
- 本批未执行真实 MediaCrawler 采集，未修改第三方平台业务源码和上游导入记录。

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
