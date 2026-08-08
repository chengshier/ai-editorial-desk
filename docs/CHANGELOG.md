# 文档与架构变更记录

## 2026-08-08 — M3-B Embedding / Vector Recall Foundation

- PR #11 已合并，基于最新 `main` `1aa6d87350f8902fec6fffeb55cee3a7905385cc` 创建独立分支 `feature/m3b-embedding-recall`，未从 `feature/m3a-event-foundation` 继续派生；
- 正式增加 Python `pgvector` dependency，并新增 `20260808_0007_m3b_signal_embeddings.py`；migration 使用 `CREATE EXTENSION IF NOT EXISTS vector` 保证数据库 capability，downgrade 不 `DROP EXTENSION vector`；
- 新增独立 `signal_embeddings`，Embedding 作为 RawSignal 之上的可重建、版本化派生 artifact，不向 `raw_signals` 回写单版本 vector；
- `signal_embeddings` 使用 `UNIQUE(signal_id, embedding_version)`，不同 embedding version 可以并存；同 version 下 input/provider/model/dimension 语义变化返回 `EMBEDDING_VERSION_CONFLICT`，不 silent overwrite；
- 向量列采用 dimensionless `VECTOR()`，每条 artifact 保存 `dimensions`，PostgreSQL CHECK 保证 `dimensions > 0`、`vector_dims(embedding) = dimensions`、`vector_norm(embedding) > 0`；
- 建立确定性 `signal-text-v1` input schema，只使用规范化后的 RawSignal `title + text`，最终 Provider 输入计算 SHA-256 保存 `input_hash`；空内容返回 `NO_EMBEDDABLE_TEXT`，不 embed 空字符串或 URL；
- 建立 Embedding 专用 `EmbeddingProvider` Protocol 与 request/result domain objects，只表达 provider/model/version/dimensions/batch vectors/可选 usage-latency-error metadata；不实现通用 AI Gateway，也不注册生产 Fake Provider；
- 新增 `EmbeddingBatchProcessor` / `EmbeddingService`，支持受控 batch、已存在 skip、有限 retry、provider wrong result count、dimension mismatch、NaN/Infinity/zero vector 等明确失败；Provider 调用位于数据库事务之外；
- 并发写入继续采用 PostgreSQL `INSERT ... ON CONFLICT DO NOTHING` + UNIQUE 作为最终保护；两个 Worker 同 signal/version 最终只保留一个 artifact；
- 新增 PostgreSQL exact cosine recall，只比较相同 `embedding_version + dimensions`，排除自身，支持 top_k、min_similarity 和时间窗，统一 `similarity = 1 - cosine_distance`；
- 新增只读 Admin metadata / recall API，不返回完整 vector 或 RawSignal `raw_payload`，也不允许客户端指定任意 Provider URL/API Key；
- 本批不创建 HNSW / IVFFlat；当前优先保证版本化、维度隔离和 exact recall 正确性，ANN 后置到有真实规模依据的性能阶段；
- M3-B Recall 只返回候选，不实现 Dedup/Clustering，不自动创建/合并 Event，不自动写 `EventSignal attached_by=embedding`，不创建 Event centroid；
- PostgreSQL 16 + pgvector 业务实现 CI 已通过：Ruff success；mypy **143 source files**；pytest **297 passed / 1 warning**；Alembic `upgrade head → downgrade -1 → upgrade head → downgrade base → upgrade head` success；Definition 第二次同步 `created=0 / updated=0 / unchanged=11 / failed=0`；Web lint/typecheck/test/build success；
- M2 状态继续保持 `M2 Engineering Complete`、`M2 Real Smoke Validation = DEFERRED / NOT_TESTED`、`M2 Real-world Validation = NOT COMPLETE`；M3-B 不访问真实平台，也不把任何 Validation 改写为 PASSED；
- 当前状态正式记录为 `M3-A COMPLETE`、`M3-B COMPLETE`、`M3-C / M3-D NOT STARTED`、`M3 Overall NOT COMPLETE`。

## 2026-08-08 — M3-A Event / EventSignal Foundation

- 基于 PR #10 合并后的最新 `main` `f36d8f26dd0b282c2465bf09bd9fdadc0081d2ae` 创建独立分支 `feature/m3a-event-foundation`，未从 M2 feature 分支继续派生；
- 新增正式 `events` / `event_signals` PostgreSQL 模型与 `20260808_0006_m3a_event_foundation.py` migration，不修改 M1/M2 历史 migration；
- Event 建立 `emerging / growing / stable / declining / resolved` 合法状态结构，M3-A 仅保守默认 `emerging`，不实现 Trend Engine 自动状态转换；
- Event 的 `summary / category / primary_language` 允许为空，`entities / keywords` 默认空结构；title 由人工填写，不调用 AI 伪造摘要或分类；
- EventSignal 建立 `origin / report / repost / reaction / official_response / correction` relation 与 `rule / embedding / llm / human` attached_by 数据结构，但本阶段 Admin 写入只允许当前真实存在的 `human`；
- EventSignal 使用 PostgreSQL `UNIQUE(event_id, signal_id)`、`INSERT ... ON CONFLICT DO NOTHING` 与 Event 行级 `FOR UPDATE` 共同保证重复/并发 attach 幂等；没有对 `signal_id` 单独加 UNIQUE，同一 RawSignal 可关联多个 Event；
- `confidence` 在 API / Service 拒绝 NaN、Infinity 与越界值，并由 PostgreSQL CHECK 保证 `0 <= confidence <= 1`；
- `source_count = COUNT(DISTINCT RawSignal.source_id)`，`platform_count = COUNT(DISTINCT RawSignal.platform)`，attach / detach 后从真实关系重算，不信任客户端计数；
- `first_seen_at = MIN(COALESCE(RawSignal.published_at, RawSignal.collected_at))`，空 Event 为 NULL；detach 后按剩余来源重算，不用当前时间伪装历史首次出现时间；
- `last_updated_at` 表示 Event 处理层最后一次有效业务变更：manual create、首次有效 attach、有效 detach 推进；重复 attach 与 no-op detach 不推进；
- 新增 `packages/events/` Repository / Service，继续复用现有 AsyncSession、AuditLog、Admin Token 与 `X-Actor-ID`，不建立第二套数据库生命周期；
- 新增最小 Admin API：create/get/list Event、list/attach/detach EventSignal；EventSignal 响应不暴露 RawSignal `raw_payload`；不开发 M5 Event Workbench；
- Event 层保持 RawSignal 采集事实不可变：attach/detach/失败事务不修改 `original_url/canonical_url/external_id/collected_at/raw_payload/platform/source_id`，detach 不删除 RawSignal；
- Connector / CollectorRuntime 热路径未接入 Event，采集成功后不要求同步创建 Event，M3 Processing 与采集层继续解耦；
- PostgreSQL 测试覆盖 Event CRUD、并发重复 attach、FK/UNIQUE/CHECK/INDEX、聚合计数、时间语义、同一 RawSignal 多 Event、RawSignal 不可变与 Admin API；
- 业务实现 HEAD `c9db09bce9c7c41229594bb7d346b47899dc8291` 对应 GitHub Actions **CI #183**（run id `31247490678`）completed / success：Ruff success；mypy **134 source files**；pytest **263 passed / 1 warning**；Alembic `upgrade head → downgrade -1 → upgrade head → downgrade base → upgrade head` 全部 success；Definition 第二次同步 `created=0 / updated=0 / unchanged=11 / failed=0`；Web lint/typecheck/test/build 全部 success；
- 新增 `docs/M3_ACCEPTANCE_REPORT.md`，正式记录 `M3-A COMPLETE`；`M3-B / M3-C / M3-D NOT STARTED`，不表述为 `M3 COMPLETE`；
- 本批未调用 OpenAI、云/本地 Embedding、Ollama、vector similarity、HNSW/IVFFlat、SimHash/MinHash、semantic similarity、自动事件匹配、Dedup/Clustering、Merge/Split 或 AI Editorial Scoring；
- M2 状态继续保持 `M2 Engineering Complete`、`M2 Real Smoke Validation = DEFERRED / NOT_TESTED`、`M2 Real-world Validation = NOT COMPLETE`，进入 M3 Engineering 不会把任何真实平台 Validation 改写为 PASSED。

## 2026-08-08 — M2-D Engineering Closure / Real Smoke Deferred

- 正式采用阶段语义：`M2 Engineering Complete`；`M2 Real Smoke Validation = DEFERRED / NOT_TESTED`；不表述为 `M2 Real-world Validation Complete`；
- M2-A / M2-B / M2-C 工程完成，M2-D offline engineering/readiness 已完成；PR #10 合并后允许从最新 `main` 独立进入 M3 Engineering；
- B站 low-volume normal search compatibility 已完成：复用 pinned client 已有 `page_size`，`requested_limit=1/3/5` 时真实 client page-size 为 1/3/5，不请求 20 后再本地截断；
- 知乎 low-volume normal search compatibility 已完成：复用 pinned `page_size → offset/limit`，`requested_limit=1/3/5` 时真实 client page-size 为 1/3/5，不新增或猜测 API 参数；
- 微博 pinned client 没有已证实的 `page_size/count/limit`，因此 `WEIBO_LOW_VOLUME_SEARCH = BLOCKED`，并正式接受为 `Accepted Known Limitation`；不猜参数、不逆向接口、不扩展 Signature、不通过本地截断伪造低量请求；
- 新增 dedicated M2-D Smoke Harness，真实执行继续限制 `requested_limit<=5`、detail=1、comments<=5、subcomments=false、concurrency=1、proxy=false、visible existing CDP、人工 actor/confirmation 与 Risk Guard；
- 新增 `docs/M2_REAL_SMOKE_SETUP.md`，覆盖 Python/Node/PostgreSQL/pgvector、双 venv、Migration、Definition sync、API/Web、低价值 Account、Browser Profile、极低 Budget、CDP 9222、Detail/Search/Comments、Run/Checkpoint/RiskEvent、真实 Validation 与停止清理；
- 新增 `python -m scripts.check_m2_smoke_environment`，只读检查本地 DB/migration/Definitions/pinned vendor/CDP/Profile/Account/Budget/Risk/Validation，不访问平台、不读取 Cookie、不创建 Run、不自动修复账号；
- 新增 `python -m scripts.check_m2_smoke_login`，仅供未来人工登录后执行；先要求 environment gate READY，再只连接 existing localhost CDP 判断预期 Cookie 名称是否存在，不读取 Cookie value、不导航平台页面、不发内容请求、不写 Validation；
- 最终 M2-D 工程 HEAD `54149c4fa83922a270a8fe10eaed4499945ca0e6` 对应 GitHub Actions **CI #177**（run id `31242273861`）completed / success；
- CI #177：Ruff success；mypy **128 source files**；pytest **240 passed / 1 warning**；Alembic 完整往返 success；Definition 第二次同步 `created=0 / updated=0 / unchanged=11 / failed=0`；Web lint/typecheck/test/build success；
- 当前 B站 / 知乎 / 微博 Real Smoke 全部 NOT_TESTED，Real Run ID 均无，Validation 均 NOT_TESTED；不存在真实 PASSED Validation；
- M5 宣布真实世界 / Production Validation 完成之前，必须至少补一次真实端到端平台 Smoke；未来优先从 B站或知乎开始；
- 本次为纯文档与阶段状态收口，不新增 M3 Event / Embedding / Dedup / Clustering / AI 功能。

## 2026-08-07 — M2-B 七平台映射与配置 Schema 收口

- 基于 PR #7 已合并后的最新 `main` 创建独立分支 `feature/m2b-platform-mappers`，未从 M2-A feature 分支继续派生；
- 新增 MediaCrawler 七个平台独立 Mapper 与显式 Platform Mapper Registry，按 pinned vendored store/model 的真实 JSONL 字段映射，不使用万能 Mapper，也不使用随机 UUID 代替平台稳定 ID；
- 建立统一 Platform Spec，以同一份真实能力声明生成七平台 `capabilities`、`config_schema`、`ui_schema` 与 `allowed_modes`，并在 Runtime preflight 中阻止不支持模式在 subprocess 前启动；
- 七平台 Definition 的 `implementation_version` 统一更新为 `mediacrawler-m2b-v1`，未来 Mapper / Schema 行为变化可触发 Validation 失效语义；
- 当前有效能力保持保守：微博/B站/抖音/快手/贴吧开放 search/detail/creator/comments；知乎开放 search/detail/comments，creator 当前有效能力为 false；小红书当前仅开放 search，并允许 search 附带 comments；七平台 homefeed/hotlist 均未开放；
- 新增统一 `CollectedComment` Domain Model，包含平台、主内容 external ID、评论 ID、作者、正文、发布时间、点赞数、父评论 ID 与脱敏 raw payload；
- 新增 PostgreSQL `raw_signal_comments`，通过独立 `20260807_0005_m2b_comments.py` migration 管理，FK 绑定 `raw_signals`、`ON DELETE CASCADE`，未修改 M1/M2-A 已合并 migration；
- 评论幂等规则集中管理：优先使用 `platform + content_external_id + external_comment_id`；无稳定 comment ID 时回退到 `platform + content_external_id + author_id + normalized_text_hash + published_at`，最终生成版本化 SHA-256 幂等键；
- 评论数据库写入使用 PostgreSQL UNIQUE + `INSERT ... ON CONFLICT DO NOTHING` 提供并发最终保护，不使用“先查再插”作为唯一约束；
- 评论按独立短事务持久化，单条评论失败不会回滚已经成功的 RawSignal；主内容成功、部分评论失败可形成 PARTIAL；整批主内容完全无法识别时整体 `PARSE_ERROR`，防止错误格式污染数据库；
- 评论默认关闭，subcomments 默认关闭，单内容 `comment_limit` 保持低上限；评论 Budget 在 Adapter/subprocess 前按 `requested_items × per-item comment_limit` 预留，预算不足时不启动 Adapter；
- 正式接通 `MediaCrawlerResultEnvelope → Platform Mapper → RawSignal / CollectedComment → CollectionResult → CollectorRuntime ingestion`；
- 增强 Web 现有动态 `SchemaForm` 的 mode 条件显示与 array enum checkbox-group，继续复用单一动态表单，不为七个平台建立独立 React 页面；
- 七个平台均增加脱敏 Fixture，严格基于当前 vendored 数据结构构造，覆盖正常主内容、可选字段缺失、malformed、metrics、media、comments、UTC 转换与 Cookie/Token/Authorization/API Key/Session/Password 等敏感字段脱敏；
- **本批未修改 `third_party/MediaCrawler/` 内任何 vendored source**，MediaCrawler 继续固定上游 commit `071c8c0acaece3e82f2532cffb19faeddc9ec1c3`，许可证保持 `NON-COMMERCIAL LEARNING LICENSE 1.1`；
- 本批全部使用 Fixture / Fake Result Envelope / Mock / PostgreSQL CI，不连接真实平台、不登录、不扫码、不使用真实 Cookie，也不把任何平台自动标记为真实 validated PASSED；
- GitHub Actions **CI #109 success**：`ruff check .` 通过、`mypy apps packages` 通过、PostgreSQL **166 passed**；
- Alembic `upgrade head → downgrade -1 → upgrade head → downgrade base → upgrade head` 完整往返通过；
- Connector Definition 连续同步两次保持幂等，第二次 `created=0 / updated=0 / failed=0`；
- Web `lint`、`typecheck`、**6 个 test files / 9 tests** 与 production build 全部通过；
- M2-B 已完成开发与 CI 验收，当前等待 PR #8 合并；M2-C / M2-D 均未开始，M2 整体尚未完成。

## 2026-08-07 — M2-A MediaCrawler 主系统集成层

- 基于 PR #6 合并后的完整 M1 `main` 新建独立分支 `feature/m2a-mediacrawler-integration`，未从 M1 feature 分支继续派生；
- 新增版本化 `MediaCrawlerInvocation` / `MediaCrawlerResultEnvelope` 协议，当前 `protocol_version=1.0`，仅传 JSON 可序列化 Domain Model，不传 ORM、Session、DATABASE_URL、Admin Token 或明文 Cookie/Token；
- 新增标准 Adapter Error Mapping，覆盖 subprocess timeout/cancel/nonzero、结果缺失/过大/损坏、protocol mismatch、browser disconnect、认证/登录/权限/限流/CAPTCHA/账号异常/自动化检测/网络超时/解析失败等；
- 增强现有 Risk Guard 风险识别，403、406、429、CAPTCHA、登录失效、账号 blocked/restricted/abnormal、自动化检测、`-104` 等风险候选不进入普通 retry；
- 新增 `MediaCrawlerSubprocessRunner`：每 Run 独立安全临时目录、主系统控制 `--save_data_path`、JSONL 结果边界、结果与诊断大小限制、timeout/cancellation 终止、结果路径逃逸与 symlink 防护；
- stdout/stderr 只作为受限诊断，不再从随机 stdout JSON 文本获取业务数据；
- subprocess 环境使用白名单，不继承 DATABASE_URL、Admin Token 或凭据环境，并显式设置 `--enable_ip_proxy false`；
- 新增 `MediaCrawlerConnector` 并注册到现有 Implementation Registry，继续通过 `CollectorRuntime` 执行，不创建第二套 Runtime/Registry；
- CollectorRuntime 仅向 Connector 补充当前 `run_id`、Definition platform 与不透明 account/profile 引用；现有 Budget、Run 原子领取、RawSignal 幂等、Checkpoint 与 Risk Guard 事务边界保持不变；
- `connector_checkpoints` 继续是权威，Invocation 可携带 checkpoint，Result 可返回 candidate，最终只在 RawSignal 成功提交后由 Runtime 推进；
- M2-A 只支持最小公共标准 item → RawSignal 边界，不实现七平台完整字段 Mapper；七平台专属 Mapper/Schema 仍属于 M2-B；
- 新增离线 Fixture/Fake subprocess 测试，覆盖 Invocation/Result、timeout/cancel/nonzero/no-result/malformed/partial、403/406/429/CAPTCHA/login-expired/permission/automation/account-restricted/network-timeout/browser-disconnect；
- 新增 PostgreSQL Runtime 集成测试，覆盖 `CollectionTask → CollectorRuntime → MediaCrawlerConnector → Fake Adapter → RawSignal`、幂等、Checkpoint 成功后推进、入库失败不推进、风险进入 `PAUSED_RISK`、Budget 在 Adapter 前生效；
- M2-A 全部测试离线完成，不连接真实平台、不登录、不扫码、不使用真实 Cookie，也不生成真实 PASSED validation；
- 新增 `docs/MEDIACRAWLER_LOCAL_CHANGES.md`，记录 pinned upstream、许可证、协议、Runner、错误、Risk、Runtime/Checkpoint 边界和本地修改范围；
- MediaCrawler 继续固定上游 commit `071c8c0acaece3e82f2532cffb19faeddc9ec1c3`，许可证保持 `NON-COMMERCIAL LEARNING LICENSE 1.1`；
- **本批未修改 `third_party/MediaCrawler/` 内任何 vendored source，也未更新上游版本**；
- 未进入 M2-B / M2-C / M2-D，也未进入 Event、Embedding、去重、聚类或 AI。

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
- M1 工程开发与 CI 验收完成，PR #6 后续已人工合并进入 `main`。

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
