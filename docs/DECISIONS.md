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

## D-021 M3-B Embedding artifact 与 exact recall

Embedding 在 M3-B 中正式定义为 RawSignal 之上的**可重建派生数据**：

- 使用独立 `signal_embeddings`，不在 `raw_signals` 直接放单版本 vector；
- Embedding artifact 按 `UNIQUE(signal_id, embedding_version)` 版本化，同一 Signal 的历史版本可以并存，模型升级不得覆盖旧向量；
- `embedding_version` 表达 input schema、preprocessing、provider/model 配置与 dimensions 的稳定组合语义，不等同于 `model_name`；同 version 下输入或配置语义变化必须报冲突并要求升级 version；
- 当前 `input_schema_version = signal-text-v1`，只使用规范化后的 RawSignal `title + text`，最终实际 Provider 输入计算 SHA-256 保存 `input_hash`；
- Python 正式使用 `pgvector` ORM integration，向量列采用 dimensionless `VECTOR()`，每条 artifact 单独保存 `dimensions`；Recall 只能比较相同 `embedding_version + dimensions`；
- Alembic 从 M3-B 起使用 `CREATE EXTENSION IF NOT EXISTS vector` 保证数据库能力可用；downgrade 不 `DROP EXTENSION vector`，因为 extension 是共享数据库能力；
- M3-B 使用 PostgreSQL **exact cosine recall**，统一 `similarity = 1 - cosine_distance`，similarity 越大表示越相似；
- M3-B 不建立 HNSW / IVFFlat。ANN 只有在真实数据规模证明 exact search 不可接受时，才进入后续性能阶段设计与调优；
- Recall 只返回相似候选，不执行 Dedup / Clustering、不自动创建或合并 Event、不自动写 `EventSignal attached_by=embedding`；M3-C 才消费这些候选形成聚类判断；
- M3-B 只建立 Embedding 专用 Provider Protocol，不实现通用 AI Gateway；生产代码不注册 Fake Provider，测试 Provider 仅存在于 tests；通用 Provider/Model Routing、Chat Completion、Prompt Registry 等仍属于 M4。

## D-022 M3-C 使用确定性聚类并让人工边界拥有最高优先级

M3-C 的自动聚类必须是可解释、可重放的确定性工程链，而不是把 LLM 作为默认事件裁判：

- exact duplicate 复用 RawSignal 的 canonical URL、content hash、platform + external ID 等已有事实语义；
- near duplicate 使用版本化 deterministic 64-bit SimHash，当前版本 `fingerprint-text-v1 + simhash64-v1`；
- 语义候选严格复用 M3-B PostgreSQL exact cosine recall，不建立第二套 vector index 或 recall Service；
- `signal_match_decisions` 按 canonical signal pair + `event-match-v1` 保存不可变判断与证据；
- 自动 assignment 使用中性 `EventSignal.relation=related`，不通过算法猜测 origin/report/reaction；
- human same/distinct override、event suppression、Merge / Split 的人工边界优先于自动重跑；
- Split / detach 后写 suppression 或 distinct override，防止下一轮自动聚类立即把人工纠错反转；
- 同 Signal 并发 assignment 通过 RawSignal `FOR UPDATE` 与 write-time membership recheck 收敛；
- CollectorRuntime 继续停在 RawSignal 边界，不同步进入聚类热路径；
- 当前不引入 MinHash、HNSW/IVFFlat、Event centroid 或 LLM event judge。

## D-023 M3-D 采用离线评测、dry-run-first 重处理与工程完成口径

M3-D 负责把 M3-C 从“有聚类实现”收口为“可评测、可重放、可安全重处理”的工程系统：

- 固定 `m3-clustering-eval-v1` synthetic/manual 工程评测集，显式记录 same/distinct/ambiguous、cluster expectation 与 human override；
- 评测输出 pair precision/recall/F1、coverage/abstention、cluster pairwise metrics、overmerge、fragmentation 等确定性指标；
- threshold sweep 只做 bounded read-only 比较，不把当前小样本最优值自动写回生产 policy；
- 新增 `clustering_processing_runs` 记录 evaluate/dry-run/apply 的版本、actor、范围、计数和配置快照；
- 新增 append-only `event_assignment_records` 保存 assignment provenance；
- reprocess 必须显式限定 signal IDs 或完整时间窗，并受 `max_items` 限制；默认 dry-run，apply 必须 actor + explicit confirmation；
- reprocess 不提供 automatic detach policy，且 apply 前重新校验 human membership、distinct override、suppression、Event 与 membership 状态；
- processing-order、batch-boundary、replay、concurrency 与 human-boundary 必须由 PostgreSQL 回归验证；
- 性能阶段只记录 exact recall + clustering engineering baseline，不把共享 CI Runner 绝对毫秒数当作生产 SLA；没有数据规模证据前不引入 ANN。

M3 的最终完成语义调整为 **M3 Overall Engineering COMPLETE**：Event、版本化 Embedding artifact/exact recall、确定性 Dedup/Clustering、人工边界、离线评测、安全重处理、provenance 与 convergence 已形成工程闭环。

早期 V1.2 M3 中的生产云 Embedding Provider、Provider UI、通用模型路由、成本中心与 LLM event judge，不再为了 M3 阶段标签提前实现；这些能力与 AI Gateway 一并进入 M4。该调整不否认长期路线，只是明确当前模块边界与交付顺序。

M3 Engineering COMPLETE 同样**不表示** M2 Real Smoke 已通过：M2 仍保持 `DEFERRED / NOT_TESTED` 与 `Real-world Validation NOT COMPLETE`。

## D-024 M4-A 采用 Task Route 驱动的 AI Gateway、opaque credential 与不可变调用审计

M4-A 正式建立通用 AI 基础链：

```text
Business Task
→ AI Task Route
→ Provider / Model
→ AIGateway
→ Invocation / Attempt
→ Usage / Cost / Audit
→ AI Budget reserve / settle
```

核心决策：

- **业务代码不得硬编码 Provider URL、商业模型名或 provider_key。** 业务只传稳定 `task_key`，Route 决定 primary/fallback Provider/Model；`model_key` 是内部稳定引用，`model_name` 只表达供应商实际名称；
- Provider 数据库类型只表达协议级 adapter（当前 `openai_compatible` / `local_openai_compatible`），不把 `gpt-*`、`claude-*`、`gemini-*` 等具体模型写成 enum；OpenAI 官方兼容端点与其他 compatible 服务优先复用同一 adapter；
- **Credential 使用 opaque reference。** M4-A 不建设完整 Vault/KMS，只增加受控 `env://NAME` resolver；DB 绝不保存 API Key 明文，API/Web/日志不返回 Key、Authorization 或原环境变量名，Web 只允许 replace credential；Provider/Model config 中的敏感键必须拒绝或脱敏；
- Provider base URL 只允许 HTTP/HTTPS，禁止 `file://`、URL userinfo、任意 shell 与隐式 redirect；HTTP 和 private/localhost endpoint 都要求显式管理员策略打开，不能把“支持本地模型”解释为无条件开放内网 SSRF；无 credential 必须在 DNS/网络动作前返回 `CREDENTIAL_NOT_CONFIGURED`；
- `AIGateway` 只提供通用 `embed` / `generate_text` / `generate_structured`，不出现 Evidence、Score、Script 等业务方法；Provider adapter 只消费领域对象，不访问业务 ORM，不把第三方 SDK/HTTP response 穿透业务层；
- Route 使用**版本化行**而不是原地覆盖：`(task_key, version)` 唯一，每个 task 只有一个 active version；配置更新关闭旧 active row 并创建 `version+1`。历史 Invocation 固定保存 `route_id / route_version / provider_key / model_name`，后续 Route 修改不得改变历史解释；
- `ai_invocations` 表达一次逻辑调用，`ai_invocation_attempts` 表达有限 retry/fallback 的每次实际 Provider attempt；调用只保存 SHA-256 `input_hash`、prompt/schema version、usage、latency、request id、错误、pricing snapshot 与可选 subject trace，默认不保存完整 Prompt/body/vector；`subject_type/subject_id` 是可扩展 trace，不伪造不存在的 polymorphic FK；
- Retry 只允许 timeout、temporary network、429 与明确 selected 5xx/invalid response 等可恢复错误；route/provider retry 取较小值并 hard cap 3；auth、invalid request、model not found 不无限 retry；Retry-After 只有在受控最大等待时间内执行；
- Fallback 必须来自 Route 显式顺序，每次 fallback 都形成 Attempt，保留从哪个 Provider/Model、为什么失败、retry/fallback index；AI Provider 429 是 AI Gateway 错误，不写入 MediaCrawler `PlatformRiskEvent`；
- Structured Output 使用 JSON Schema 做通用 contract 校验；malformed JSON、missing field、wrong type、refusal 必须失败；repair/retry 仍受 bounded retry 约束；Gateway 本身不理解 EvidenceClaim 语义；
- **Pricing 不硬编码在业务代码。** Model 保存可空 input/output/embedding price 与 `pricing_version`，Invocation/Attempt 固化当时 pricing snapshot 和最终 estimated cost；后续调价不得覆盖历史成本；Provider 无 usage 或价格未知时保持 unknown，不伪造成本 0；
- **AI Budget 与 CollectionBudget 分离。** 第一版只支持 global/task/provider scope、daily/monthly cost 与 daily tokens；调用前 reserve、调用后 settle。PostgreSQL 对适用 Budget 行 `FOR UPDATE`，monthly 聚合在同一 Budget 锁保护下计算，避免并发 Worker 双花预算；未知成本默认 `block`，可显式 `allow_once`，但也必须通过原子 reservation/counter 限制，不能把 NULL 当 0 无限调用；
- Provider 网络调用不得持有长数据库事务；Route snapshot、Invocation、Budget reservation/settlement 都采用短事务边界；
- M3-B `EmbeddingProvider` Contract、`EmbeddingService`、`EmbeddingBatchProcessor`、`signal_embeddings` 与 exact vector recall 保持不变。M4-A 只增加 `GatewayEmbeddingProvider` 生产桥接；bridge 锁定 `embedding` Route 的 primary snapshot 并要求显式 `embedding_version + dimensions` 一致，避免 fallback 静默改变 M3-B artifact 版本语义；本批不自动 backfill 全库；
- CI 的 AI 测试必须使用 Fake/Stub/MockTransport，不访问公网或真实付费模型。Fake/Mock success 只能证明 engineering contract，**不能**把 Production Provider Validation 写成 PASSED/VERIFIED；没有人工 credential + 真实网络 Provider call 时保持 `NOT_TESTED`；
- Provider connection test 必须是单个极小受控输入，记录 `test=true` Invocation、usage/cost，并且没有 credential 时明确返回 `CREDENTIAL_NOT_CONFIGURED`，不能自动 fallback 到 Fake 或其他环境中的陌生 key；
- M4-A 只注册 `embedding / event_boundary_review / evidence_extraction / editorial_scoring / draft_generation / final_review` task route 能力；除 M3-B embedding bridge 外，本批**不消费** Evidence、Editorial、Draft 路由，不接入 LLM event judge，不修改 M3 clustering 结果、评测 ground truth 或 threshold。

因此当前阶段语义为：

```text
M4-A AI Gateway Engineering COMPLETE
Production AI Provider Validation NOT_TESTED
M4-B NOT STARTED
M4-C NOT STARTED
M4-D NOT STARTED
M4 Overall NOT COMPLETE
```

## D-025 M4-B Evidence 必须具备 RawSignal provenance，AI 只有候选权限，Human verification 优先

M4-B 的目标是建立“当前有哪些可追溯事实候选、争议和未知项”，而不是建立自动新闻真伪裁判。

正式决策：

- **EvidenceClaim 必须有具体 RawSignal provenance。** AI 或 Human 新增的 source 必须通过 `EventSignal(event_id, signal_id)` 属于目标 Event；无 supporting/contradicting source 的模型陈述不进入 Claim 表，当前统一记为 `UNSUPPORTED_CLAIM`；
- Evidence source 正式使用 `evidence_claim_sources` 真实 FK 关联表，而不是在 Claim 保存裸 UUID 数组；`UNIQUE(claim_id, signal_id)` 保证一个 Signal 在同一 Claim 不同时扮演 supporting/contradicting；`signal_id → raw_signals.id` 使用 `ON DELETE RESTRICT`，防止清理 RawSignal 时历史证据静默消失；
- Claim 类型固定为 `fact / allegation / opinion / forecast`；verification 状态固定为 `confirmed / investigating / single_source / disputed / false`，第一版不扩张更多未经验证状态；
- **AI 无权自动写 `confirmed` 或 `false`。** 模型即使在结构化输出中自行声称 confirmed/false，Evidence Service 也必须忽略；AI 初始状态只按实际来源关系推导：存在 contradiction 为 `disputed`，仅一个 support 为 `single_source`，多个 support 且无 contradiction 为 `investigating`；`extraction_confidence` 只表示抽取置信度，不等于事实真实性；
- **Human verification 优先于 AI rerun。** confirmed 至少需要一个 supporting source；false 至少需要一个 contradicting source；两者都要求 Human Actor + 明确 reason/editor note + AuditLog。AI 重跑只能幂等补充已有来源，不能把已人工确认状态降回 investigating/single_source/disputed，也不能覆盖人工 editor note；
- confirmed Claim 不允许删除最后一个 supporting source，false Claim 不允许删除最后一个 contradicting source。本批不暴露 Claim hard-delete API，人工验证历史不能通过正常 Admin API 无痕消失；
- `EventUnknown` 是一等业务对象，不用“事故时间不明”之类伪 Claim 代替未知项；Unknown 在 Event 内按 stable fingerprint 幂等，`resolved / dismissed` 后 AI rerun 不自动 reopen，只有明确 Human 操作可改变生命周期；
- Claim fingerprint 使用 `SHA-256(claim_type + normalized claim_text)`；Unknown fingerprint 使用规范化文本 SHA-256；PostgreSQL UNIQUE + `ON CONFLICT` 是并发幂等最终保护；
- 如果 `event.merged_into_event_id IS NOT NULL`，旧 source Event 禁止新增或修改 Evidence，返回 `EVENT_MERGED + target_event_id`。历史 Evidence 可读取，但新的 Evidence 必须挂到 merge target；M4-B 不改变 M3 Event clustering、ground truth 或 threshold；
- Evidence 输入只允许 Event + EventSignal + 安全 RawSignal 字段：signal ID、title/text、author、platform、published/collected time 与 URL metadata；默认禁止 `raw_payload`、credential、Cookie、Authorization、connector config、完整 comment dump 与 Embedding vector；
- 输入必须 bounded 且 deterministic：显式 signal IDs 或 `max_signals`，同时限制 `max_chars_per_signal / max_total_chars`；按 `COALESCE(published_at,collected_at), signal_id` 排序；截断必须记录 `truncated=true` 与 signal IDs，不能无声截断；
- Prompt 与 Schema 独立版本化，当前固定 `evidence-extraction-v1` / `evidence-schema-v1`；RawSignal 正文在 Prompt 中明确标记为 **UNTRUSTED CONTENT**。Prompt 要求模型不得执行帖子中的指令，但安全不能只靠 Prompt：Service 必须二次校验 Event、membership、source role、confidence、unsupported claim 与 AI verification 权限；
- Evidence extraction 必须通过 M4-A `AIGateway.generate_structured(task_key=evidence_extraction)`，继续经过 Route、Budget、bounded retry、fallback、schema validation、Invocation/Attempt、usage/cost；业务层不得直接 HTTP 调 Provider，也不得复制第二套 JSON repair；
- Invocation 固定记录 `subject_type=event`、`subject_id=event.id`、prompt/schema version；`EvidenceExtractionRun` 只表达业务执行与 Invocation 关联，不重复保存 Provider token/cost 日志；
- Provider 网络调用继续位于数据库长事务之外：先短事务获取安全 snapshot，再调 Gateway，最后新短事务重新检查 Event 未 merged 与 signal membership 后 apply；
- Preview 可以产生真实 Invocation 和费用，但不写 Claim/Unknown，不能称为 free preview；
- 局部脏 structured result 采用 **PARTIAL**：合法项保存，无来源/错误 source 的 item 明确记录 invalid count/code；不静默丢弃后把整批标记 success，也不因为单个坏 item 自动回滚全部合法 Evidence；
- route disabled、credential missing、budget exceeded、provider unavailable、malformed/schema-invalid 输出必须明确失败，绝不 fallback 到 Fake 或凭空生成 Claim；人工 Claim/Verification 流程在 Production Provider `NOT_TESTED` 时仍可使用；
- CI 的 Evidence AI 测试全部离线使用 MockTransport/Fake。Fixture success 只能证明工程 contract，不能改变 `Production AI Provider Validation = NOT_TESTED`；
- M4-B 不建立 Source Credibility 评分，不实现 Trend / Editorial Score，不生成 Event Card、Draft、Script、标题、封面文案或素材包。

因此阶段语义更新为：

```text
M4-A AI Gateway COMPLETE
M4-B Evidence / Claim COMPLETE
Production AI Provider Validation NOT_TESTED
M4-C NOT STARTED
M4-D NOT STARTED
M4 Overall NOT COMPLETE
M5 NOT STARTED
```
