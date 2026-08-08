# 项目决策记录

## D-001 仓库结构

采用一个主仓库。MediaCrawler 放在：

```text
third_party/MediaCrawler
```

MVP 阶段由主系统通过 Adapter 启动 MediaCrawler 子进程。

## D-002 模块边界

MediaCrawler 只负责平台采集。事件聚类、AI 评分、证据链、稿件、Provider 管理、工作台和复盘属于主系统。

## D-003 数据库

采用 PostgreSQL + pgvector，通过 Docker Desktop 运行。默认将宿主机 `55432` 映射到容器 `5432`，避免与本机其他数据库环境混淆。

## D-004 AI 策略

MVP 默认使用云 Embedding 和低价云 LLM，同时保留 OpenAI-compatible 与本地 Ollama Provider 接口。

## D-005 配置方式

连接器、AI Provider、任务路由和调度采用可视化配置。YAML/JSON 只用于初始化、导入导出、迁移和备份。

## D-006 MediaCrawler 增强范围

只吸收以下五项：

1. 断点续采；
2. 增量采集；
3. 账号、浏览器 Profile 与可选代理抽象；
4. 签名逻辑解耦；
5. 有限 HomeFeed 与热榜补充发现。

不以复刻 Pro 为目标。

## D-007 平台账号风控

遇到验证码、权限拒绝、403、406、429、`account blocked`、检测到自动化或明确账号限制时，停止任务并进入人工检查，不自动反复登录或继续重试。

## D-008 MVP 运行形态

初期保持一个产品入口。MediaCrawler 按采集任务临时启动子进程，任务结束后退出，不要求运营人员维护第二套后台。

## D-009 Connector Definition 所有权

Connector Definition 由代码 Manifest 管理，并通过幂等命令同步到数据库：

- 使用 `connector_type + platform` 作为稳定定位键；
- 代码拥有 `display_name`、`capabilities`、`config_schema`、`ui_schema` 和 `implementation_version`；
- 数据库中的 `is_enabled` 属于运营状态，后续同步不得覆盖；
- Definition 注册只表示系统已声明该来源，不等于实现、启用或验证；
- Definition 同步不写入 Alembic migration，避免迁移依赖运行时业务逻辑。

## D-010 M1-B 管理接口保护与审计

在完整用户和 RBAC 建立前，`/api/v1/admin/*` 使用环境变量 `APP_ADMIN_TOKEN` 和请求头 `X-Admin-Token` 进行最小内部保护，修改接口额外要求 `X-Actor-ID`。

该机制仅用于内部开发阶段，不宣称为完整认证系统。配置修改使用轻量 `configuration_change_logs` 记录脱敏前后数据；M1-B 不实现完整快照回滚。

## D-011 Raw Signal 身份与幂等

Connector 输出使用独立领域模型，不能直接创建 SQLAlchemy ORM 或提交事务。Raw Signal 身份算法集中管理并固定为 `v1`：

1. 有稳定 external ID 时使用 `connector_type + platform + external_id`；
2. 否则使用 `connector_type + platform + canonical_url`；
3. 再否则使用 `source_id + content_hash + published_at`。

数据库以 `idempotency_key` 唯一约束和 PostgreSQL `ON CONFLICT` 作为并发最终保护，不允许只依赖“先查再插”。

## D-012 Collector Runtime 事务边界

Collector Runtime 不建立跨网络调用的大事务：

- 预检、Run 领取、预算预留、每批信号写入、Checkpoint 更新、Run 终态和预算结算均为短事务；
- Run 领取和终态必须使用带旧状态条件的数据库原子更新；
- Checkpoint 只跟随已经成功提交的信号推进；
- 已提交信号不会因后续单条错误或进程失败被回滚；
- 普通网络失败与平台风控事件分开处理。

## D-013 公共 URL 网络边界

RSS 与手工 URL 共享安全 HTTP 边界：

- 只允许 HTTP/HTTPS；
- DNS 返回的每个地址和 Redirect 每一跳都重新验证；
- 拒绝本机、私网、链路本地、多播、保留、未指定和云元数据地址；
- 不发送 Cookie、Authorization 或用户凭据；
- 限制跳转、连接/读取时间、响应体大小和 Content-Type；
- 错误响应不暴露内部网络、原始响应体或敏感请求头。

## D-014 M1-D Scheduler 采用数据库持久化轮询

M1-D Scheduler 采用 `asyncio + PostgreSQL` 轮询，而不是 Redis/Celery/APScheduler 内存 Job：

- `collection_schedules` 保存调度配置与下一次运行时间；
- `collection_schedule_triggers` 以 `(schedule_id, scheduled_for_at)` 唯一约束保存时间槽；
- `scheduler_instances` 保存实例 heartbeat；
- Scheduler 只生成现有 `CollectionTask` 并调用 `CollectorRuntime`，不能直接调用 Connector 绕过 Runtime；
- Budget、Risk Guard、Run 原子领取、Checkpoint 和 RawSignal 幂等继续由现有 Runtime 负责。

该设计优先满足单机/少量多实例的 M1 可靠性，不提前引入大规模 Worker 集群。

## D-015 Scheduler Lease 与崩溃恢复

同一 Schedule 的到期触发必须使用数据库条件更新取得 Lease，不能仅依赖进程 mutex。时间槽唯一约束是重复触发的数据库最终保护。

Lease 过期允许其他 Scheduler 重新取得调度所有权；如果发现上一个时间槽已经进入 RUNNING 但执行 Lease 过期，不自动盲目重跑，而是暂停该调度并要求人工检查 stale Run。

stale RUNNING Run 只提供识别、人工标记失败/取消和人工 retry。Retry 创建新的 Run，使用 `parent_run_id` / `retry_count` 保留关系，并重新经过 Budget、Risk Guard、Checkpoint 和 RawSignal 幂等；禁止无限自动 retry。

## D-016 M1 国内热榜选择百度实时热榜

M1-D 首个国内热榜选择百度官方实时热榜：

- 官方公开页面：`https://top.baidu.com/board?tab=realtime`；
- Connector 使用公开 JSON：`https://top.baidu.com/api/board?platform=wise&tab=realtime`；
- 2026-08-07 开发验收时，公开页面可直接读取榜单，JSON 入口返回 `application/json`；
- 不依赖账号登录、Cookie、验证码、签名破解、浏览器指纹或代理轮换；
- 采集保持低频、小条数、明确 User-Agent、超时、响应大小和 Content-Type 限制；
- 继续复用 SafeHTTPFetcher 的 DNS/Redirect SSRF 防护；
- CI 只使用 fixture/mock，不连接该外部来源。

公开可访问不被解释为永久授权保证。如果后续来源明确限制自动访问、出现验证码或平台风控，应立即停用并重新选择低风险公开来源，不实施绕过。

## D-017 Connector Validation 必须与真实人工验收分离

`registered`、`implemented`、`enabled`、`validated` 是四个独立状态。

M1-D 使用 `connector_validation_records` 保存 NOT_TESTED / PASSED / FAILED / EXPIRED：

- Definition 注册或 CI Mock 通过不能自动写 PASSED；
- PASSED 必须由带 `X-Actor-ID` 的人工操作写入；
- 服务端拒绝 CI/Mock 环境的 PASSED；
- PASSED 必须声明 `real_smoke_test=true` 并绑定同一 Definition 下状态为 SUCCEEDED 的 Test/Manual Run ID；
- 验真证据必须脱敏，不能保存 Cookie、Token、Authorization、API Key 等；
- implementation_version 变化后旧结果按 EXPIRED 解释。

实际外部 Smoke 仍由管理员以低量 Test Run / Manual Import 执行，继续受 Budget、Risk Guard、SSRF、Checkpoint 和幂等约束。

## D-018 M1 Web 工作台仍是内部管理 MVP

`apps/web` 使用 React + Vite + TypeScript，为 M1 提供连接器管理而不是最终编辑工作台：

- Definitions、Instances、Sources、Schedules、Runs、Checkpoints、Accounts/Risk；
- Instance/Source 的新增、编辑、启停/归档和 Test Run；
- Instance Run Now、调度 pause/resume/run-now；
- JSON Schema / UI Schema 驱动基础动态表单；
- Checkpoint reset 明确作为高风险操作；
- Admin Token 不硬编码进仓库，前端只在会话范围持有；
- 写操作继续携带 Actor；
- Web 不显示 credential_ref、browser_profile_ref、Cookie、Token、Authorization 或 API Key 原值。

完整用户登录和 RBAC 不属于 M1。

## D-019 M1 收口边界

M1 完成后只进入 M2，不在 M1-D 中提前实现 Event、EventSignal、Embedding、pgvector 相似检索、事件聚类、人工合并/拆分、AI Gateway、AI Provider、AI 评分、证据提取或稿件生成。

MediaCrawler 七个平台真实运行与五项增强同样没有在 M1-D 中提前执行。

## D-020 M2 Real Smoke 延后策略

M2 自本决策起正式区分**工程完成**与**真实平台验证完成**：

```text
M2 Engineering Complete
M2 Real Smoke Validation Deferred / NOT_TESTED
M2 Real-world Validation NOT COMPLETE
```

具体决策：

- M2-A / M2-B / M2-C 工程完成；M2-D offline engineering/readiness 完成；
- Real Smoke 可以因为本地真实联调环境暂不可用而 Deferred；
- Deferred / NOT_TESTED **不得**转换、映射或伪造为 PASSED；
- M3 / M4 / M5 Engineering 可以继续，不再因为 Real Smoke 环境暂不可用而无限阻塞；
- PR #10 合并后允许从最新 `main` 独立进入 M3-A，不从 M2-D feature branch 派生；
- 在 M5 宣布“真实世界 / Production Validation 完成”之前，必须至少补一次真实端到端平台 Smoke；
- 未来真实 Smoke 首选从 B站或知乎开始；
- 微博 `Search<=5` 当前保持 `WEIBO_LOW_VOLUME_SEARCH = BLOCKED`，并正式接受为 **Accepted Known Limitation**；
- 微博 Gate 只有在 upstream 明确提供低量参数、新 pinned version 有可验证实现，或正规源码证据证明现有接口支持低量请求时才重新打开；
- 不允许通过猜测 API 参数、接口逆向、扩展 Signature、请求 10/20 后本地截断等方式伪造低量 Gate；
- 任何未来真实 Smoke 仍必须遵守现有 Risk Guard、极低 Budget、dedicated low-value Account、stable Browser Profile、visible existing CDP、concurrency=1、proxy=false、无 proxy rotation、无自动换号、无 stealth/fingerprint/CAPTCHA 绕过等边界；
- 403 / 406 / 429 / CAPTCHA / automation detected / login expired / account restricted / blocked / abnormal 等信号出现时立即停止，不重试、不切换账号/Profile/代理。

因此，**允许 M3 Engineering 开始不代表 M2 Real Smoke VERIFIED，也不代表 M2 Real-world Validation Complete**。
