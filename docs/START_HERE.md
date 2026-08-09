# AI 编辑部项目开发入口

## 当前阶段

```text
M1 COMPLETE / 已合并
M2 Engineering COMPLETE / 已合并
M2 Real Smoke Validation DEFERRED / NOT_TESTED
M2 Real-world Validation NOT COMPLETE
M3-A COMPLETE / 已合并
M3-B COMPLETE / 已合并
M3-C COMPLETE / 已合并
M3-D Engineering COMPLETE / PR #14 已合并
M3 Overall Engineering COMPLETE
M4-A AI Gateway Engineering COMPLETE / PR #15 Open
Production AI Provider Validation NOT_TESTED
M4-B NOT STARTED
M4-C NOT STARTED
M4-D NOT STARTED
M4 Overall NOT COMPLETE
M5 NOT STARTED
```

当前 M4-A 分支：

```text
feature/m4a-ai-gateway
```

当前 PR：

```text
#15 feat: 完成 M4-A AI Gateway与模型路由基础
```

PR #15 保持 Open，不自行合并。M4-B 只有在 PR #15 人工合并后，才能从**最新 `main`**创建新的独立分支；不得从 M4-A feature branch 继续派生。

M2 Real Smoke Deferred 状态继续保留：进入 M4 Engineering 不等于微博/B站/知乎真实 Smoke 已验证，不得把 NOT_TESTED 改写为 PASSED。Production AI Provider Validation 同理：CI Fake/Mock 通过不等于生产 Provider 已真实验证。

## 必读文档顺序

1. `DECISIONS.md`
2. `M4_ACCEPTANCE_REPORT.md`
3. `M3_ACCEPTANCE_REPORT.md`
4. `M2_ACCEPTANCE_REPORT.md`
5. `M2_REAL_SMOKE_SETUP.md`
6. `AI编辑部_综合开发实施规划_V1.2.md`
7. `AI编辑部_技术开发文档_V1.2.md`
8. `AI编辑部_PRD_V1.2.md`
9. `CHANGELOG.md`
10. `MEDIACRAWLER_LOCAL_CHANGES.md`

冲突优先级继续为：DECISIONS → 综合开发实施规划 → 技术开发文档 → PRD。阶段验收报告记录当前工程事实，但不得覆盖正式架构决策。

> 基线说明：M4-A 开工清单要求读取 `docs/M3_EVALUATION_REPORT.md`，但 PR #14 合并后的最新 `main` 实际不存在该文件。M3-D 工程评测事实仍以 `M3_ACCEPTANCE_REPORT.md`、评测 fixture、评测脚本与测试为准；不得伪造历史文件存在。

## 当前正式处理链

```text
RawSignal
→ Event / EventSignal                                  M3-A
→ EmbeddingInput(signal-text-v1)
→ versioned signal_embeddings
→ pgvector exact cosine recall                         M3-B
→ deterministic fingerprint
→ exact / near duplicate
→ event-match-v1
→ automatic Event assignment + human Merge / Split    M3-C
→ offline engineering evaluation
→ convergence / replay / provenance
→ bounded dry-run-first reprocessing                   M3-D

Business Task
→ AI Task Route
→ immutable route version
→ Provider / Model
→ AIGateway
→ Invocation / Attempt
→ Usage / Cost / Audit
→ AI Budget reserve / settle                           M4-A
```

Connector / CollectorRuntime 仍停在 RawSignal 边界。M4-A 不修改 M3 clustering、evaluation ground truth 或 threshold，也不把 Provider 429 混入 MediaCrawler `PlatformRiskEvent`。

## M3-B Embedding 与 M4-A 的边界

M3-B 已有且继续保留：

- `signal_embeddings` 版本化 artifact；
- `signal-text-v1` input schema；
- `EmbeddingProvider` contract；
- `EmbeddingService` / `EmbeddingBatchProcessor`；
- pgvector exact cosine recall；
- embedding version + dimensions 隔离。

M4-A 新增 `GatewayEmbeddingProvider` 作为生产桥接：

```text
EmbeddingService
→ existing EmbeddingProvider Contract
→ GatewayEmbeddingProvider
→ task_key=embedding
→ AIGateway
→ OpenAI-compatible adapter
```

桥接只使用 route 的主模型快照，并要求模型显式声明与请求一致的 `embedding_version` 与 `dimensions`，避免 fallback 静默改变既有 M3-B artifact 语义。M4-A 没有创建第二套 SignalEmbedding、EmbeddingInputBuilder 或 Vector Recall，也没有默认全库 backfill。

## M4-A 数据基础

Migration head：

```text
20260809_0010_m4a_ai_gateway
```

新增正式表：

```text
ai_providers
ai_models
ai_task_routes
ai_invocations
ai_invocation_attempts
ai_budgets
ai_budget_usages
```

核心约束：

- `ai_providers.provider_key` unique；
- `ai_models(provider_id, model_key)` unique；
- `ai_task_routes(task_key, version)` unique；每个 task 只有一个 `is_active=true` 版本；
- Invocation 使用稳定 UUID；Attempt `(invocation_id, attempt_no)` unique；
- Budget `(scope_type, scope_key)` unique；
- token / cost / retry / fallback / usage 不允许负数。

Migration 只注册以下 task route v1，默认全部 disabled，不调用 Provider：

```text
embedding
event_boundary_review
evidence_extraction
editorial_scoring
draft_generation
final_review
```

其中 M4-A 只消费 `embedding` bridge；其余任务只建立可配置 route，不实现 Evidence、Editorial Score 或 Draft 业务。

## Provider / Credential / Network

- 业务代码只引用 `task_key`，不硬编码 Provider URL、provider_key 或商业模型名；
- Provider 类型当前实现 `openai_compatible` / `local_openai_compatible`，两者复用同一协议 adapter；
- `model_key` 是内部稳定引用，`model_name` 是供应商实际名称；
- DB 只保存 opaque `credential_ref`；M4-A resolver 仅支持受控 `env://NAME`；
- API/Web 不返回真实 credential ref 名称或明文 key，只返回 configured 状态和 `env://***`；
- Credential UI 只有 replace，没有 read-back；
- Provider config 中的 secret / api_key / authorization 等敏感键被拒绝；
- base URL 只允许 HTTP/HTTPS；禁止 file://、userinfo、query/fragment；
- HTTP 与私网/localhost 都必须显式管理员策略允许；连接测试不跟随 redirect；
- 缺 credential 时先返回 `CREDENTIAL_NOT_CONFIGURED`，不会先做 DNS/网络调用，也不会 fallback 到 Fake/陌生 key。

## Gateway / Retry / Fallback / Structured Output

正式 Contract：

```text
AIGateway.embed(...)
AIGateway.generate_text(...)
AIGateway.generate_structured(...)
```

Provider Protocol：

```text
EmbeddingGenerationProvider
TextGenerationProvider
StructuredGenerationProvider
```

- Provider 输入/输出使用 Gateway 领域对象，不把第三方 SDK/HTTP 对象穿透业务层；
- OpenAI-compatible adapter 解析 usage 与 provider request id；
- error taxonomy 覆盖 AUTH_ERROR、RATE_LIMITED、TIMEOUT、NETWORK_ERROR、INVALID_REQUEST、MODEL_NOT_FOUND、CONTEXT_LENGTH_EXCEEDED、INVALID_RESPONSE、STRUCTURED_OUTPUT_INVALID、PROVIDER_UNAVAILABLE、BUDGET_EXCEEDED、UNKNOWN_PROVIDER_ERROR；
- retry 上限为 route/provider 较小值并额外 hard cap 3；auth/invalid request/model not found 不无限重试；
- Retry-After 只有在受控最大延迟内才等待；
- fallback 只对明确允许的可恢复错误执行，并逐 Attempt 记录来源模型、目标模型、retry/fallback index 与错误码；
- structured output 先验证 JSON Schema，再验证 Provider 返回；malformed/wrong type/missing field 都不能返回 success；repair/retry 有限，不无限请求。

## Invocation / Cost / Budget

`ai_invocations` 保存逻辑调用摘要，`ai_invocation_attempts` 保存 retry/fallback 链。默认不保存完整 Prompt、Provider body、Authorization、API Key 或完整 Embedding vector。

每次调用保存/可追溯：

- task / route version；
- provider/model；
- SHA-256 `input_hash`；
- prompt/schema version；
- token usage；
- pricing snapshot / estimated cost；
- latency / retry / fallback；
- provider request id；
- error code；
- 可选 `subject_type / subject_id`，不伪造不存在的 polymorphic FK。

模型价格来自 Model 配置，不硬编码到业务代码；历史 Invocation 保存当时 pricing snapshot 和最终 estimated cost，后续价格变化不回写历史成本。Provider 没有 usage/cost 时保持 unknown，不伪造 0。

AI Budget 与 CollectionBudget 分表，支持：

```text
global
task
provider
```

调用前 reserve，调用后 settle。PostgreSQL 对适用 Budget 行 `FOR UPDATE`，并在同一锁保护下计算 daily/monthly/token 用量，避免两个 Worker 同时透支。未知成本策略默认 `block`；可显式设 `allow_once`，但也只能通过原子 reservation 放行一次未知用量。

## Admin API / Web

Admin API 前缀：

```text
/api/v1/admin/ai
```

已建立：

- Provider list/get/create/update/enable/disable/test；
- Model list/create/update/enable/disable；
- Route list/get/version update；
- Budget list/create/update；
- Invocation list/detail，只读。

继续复用现有 `APP_ADMIN_TOKEN` / `X-Admin-Token` 与 `X-Actor-ID`。Provider/Model/Route/Budget 配置写操作复用 `ConfigurationChangeLog`；Invocation/Attempt 负责 AI 调用级审计。

Web 继续使用现有 React/Vite 工作台架构，新增：

```text
AI Providers
AI Routes
AI Budgets
AI Invocations
```

不引入第二套前端路由框架，不展示完整敏感 Prompt。

## Production Provider Validation

当前状态：

```text
Production AI Provider Validation = NOT_TESTED
```

原因：M4-A CI 只允许离线 MockTransport/Fake；没有使用人工生产 credential 与真实 Provider 网络调用。Fixture/Mock 通过不得写成 `PASSED` 或 `VERIFIED`。

Connection Test 会建立 `test=true` Invocation 并计入 cost/budget；无 credential 返回 `CREDENTIAL_NOT_CONFIGURED` 并保持 Provider Validation `NOT_TESTED`。

## 最终 CI Gate

PR #15 只在**最新 exact-head**同时满足以下条件时具备人工合并资格：

```bash
ruff check .
mypy apps packages
timeout 90s pytest -q -s tests/test_clustering_reprocess_concurrency_m3d.py
timeout 180s pytest -vv
python -m scripts.evaluate_m3_clustering --format text
pytest -q -s tests/test_clustering_performance_m3d.py
alembic upgrade head
alembic downgrade -1
alembic upgrade head
alembic downgrade base
alembic upgrade head
python -m scripts.sync_connector_definitions
python -m scripts.sync_connector_definitions

cd apps/web
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

所有 AI 测试必须离线，不访问公网或真实付费 Provider。

## M4-A 完成语义

`M4-A AI Gateway Engineering COMPLETE` 表示：Provider/Model/Route、opaque credential、Gateway contract、OpenAI-compatible adapter、M3-B Embedding bridge、bounded retry/fallback、Invocation/Attempt、pricing/cost snapshot、AI Budget 并发 gate、Admin API、Web 与离线工程回归已经形成基础闭环。

它**不表示**：

- M2 Real Smoke 已通过；
- Production AI Provider 已真实验证；
- LLM event judge 已接入 M3 clustering；
- EvidenceClaim 已实现；
- Editorial Score/Trend 已实现；
- Event Card / Script / Draft 已实现；
- M4 Overall 已完成；
- M5 已开始。
