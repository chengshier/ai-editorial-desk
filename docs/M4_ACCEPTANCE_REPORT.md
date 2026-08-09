# M4 Acceptance Report

## 1. 阶段状态

```text
M4-A AI Gateway：COMPLETE
M4-B Evidence / Claim：NOT STARTED
M4-C Trend / Editorial Score：NOT STARTED
M4-D Event Card / Script：NOT STARTED
M4 Overall：NOT COMPLETE
Production AI Provider Validation：NOT_TESTED
```

M4-A 是**工程完成**口径，不代表任何生产 Provider 已真实联网验证，也不代表 M4 Overall 完成。

M2 / M3 状态继续保持：

```text
M1 Engineering COMPLETE
M2 Engineering COMPLETE
M2 Real Smoke Validation DEFERRED / NOT_TESTED
M2 Real-world Validation NOT COMPLETE
M3 Overall Engineering COMPLETE
```

## 2. 开发基线

- PR #14 已确认 `merged=true`；
- M4-A 从 PR #14 合并后的最新 `main` `e87d89a0f2861fe5f7f62010ada3f8e249ac18ef` 创建 `feature/m4a-ai-gateway`；
- 未从 `feature/m3d-evaluation-closure` 派生；
- 未直接修改 `main`；
- M4-A PR #15 保持 Open，不自行合并。

基线文档审计发现：任务清单要求读取 `docs/M3_EVALUATION_REPORT.md`，但 PR #14 合并后的 `main` 实际不存在该文件。M3-D 评测事实由 `docs/M3_ACCEPTANCE_REPORT.md`、固定评测 fixture、评测脚本与测试承载。本批未伪造该历史文件。

## 3. M4-A 数据模型

Migration：

```text
20260809_0010_m4a_ai_gateway
```

新增：

- `ai_providers`；
- `ai_models`；
- `ai_task_routes`；
- `ai_invocations`；
- `ai_invocation_attempts`；
- `ai_budgets`；
- `ai_budget_usages`。

关键约束：

- Provider `provider_key` unique；
- Model `(provider_id, model_key)` unique；
- Route `(task_key, version)` unique，并由 PostgreSQL partial unique index 保证每个 task 只有一个 active version；
- Attempt `(invocation_id, attempt_no)` unique；
- Budget `(scope_type, scope_key)` unique；
- token、cost、retry、fallback、usage 均有非负 CHECK；
- M1-M3 历史 migration 未修改。

Migration 只注册以下 route v1，全部默认 disabled：

```text
embedding
event_boundary_review
evidence_extraction
editorial_scoring
draft_generation
final_review
```

Migration 不调用真实 Provider，不产生 Evidence/Score/Draft，也不修改 M3 Event cluster。

## 4. Provider / Model

### Provider

正式 Provider 管理表达：

- stable `provider_key`；
- `display_name`；
- protocol-level `provider_type`；
- configurable `base_url`；
- opaque `credential_ref`；
- enabled / validation status；
- timeout / max concurrency / retry limit；
- sanitized config；
- created/updated actor。

当前协议 adapter 支持：

```text
openai_compatible
local_openai_compatible
```

没有把 `gpt-*`、`claude-*`、`gemini-*` 写成数据库 enum，也没有业务代码硬编码 Provider URL。

### Model

`model_key` 是系统内部稳定引用；`model_name` 是供应商实际模型名。模型声明 capability：

- `embedding`；
- `text_generation`；
- `structured_output`；
- schema 允许未来 `vision` / `audio`，但本批没有实现完整多模态。

模型保存 nullable context window、dimensions 与 input/output/embedding price，并保存 `pricing_version`。价格未知时保持 NULL。

## 5. Credential / Secret

复用项目现有 opaque reference 语义，不增加明文 secret table，也不在本批引入完整 Vault/KMS。

M4-A 新增受控 resolver：

```text
credential_ref = env://ENVIRONMENT_VARIABLE_NAME
```

保证：

- DB 不存 API Key 明文；
- Provider config 拒绝 `api_key` / `secret` / `authorization` 等敏感字段；
- API 不返回原 credential ref 名称或明文 secret；
- Web 只显示 configured 状态与 `env://***`；
- Web 只允许 replace，不提供 read-back；
- 日志/Invocation 不保存 Authorization；
- 无 credential 时先返回 `CREDENTIAL_NOT_CONFIGURED`，不先发起 DNS/网络动作，也不 fallback 到 Fake。

## 6. Gateway Contract

正式内部能力：

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

Provider adapter 只接收 Gateway 领域对象，不访问业务 ORM，不把第三方 SDK/HTTP 对象穿透业务层。

Gateway 不包含：

- `extract_evidence(...)`；
- `score_event(...)`；
- `write_script(...)`。

这些仍属于后续业务层。

## 7. OpenAI-compatible Adapter

正式 adapter：`OpenAICompatibleProvider`。

能力：

- base URL 配置化；
- credential_ref resolver；
- model 来自 Route/Model 配置；
- embedding；
- chat text generation；
- JSON-schema structured output；
- timeout；
- usage / request id 解析；
- Provider error normalization；
- private network / HTTP 显式策略；
- redirect 禁止；
- `trust_env=false`，避免隐式代理/credential 环境干扰。

OpenAI 官方兼容端点与其他 compatible 服务复用同一 adapter；没有复制品牌专用 Gateway。M4-A 不安装 Ollama、不下载模型、不管理 GPU。

## 8. M3-B Embedding Bridge

M3-B 以下能力没有重写：

- `EmbeddingProvider` Contract；
- `EmbeddingService`；
- `EmbeddingBatchProcessor`；
- `signal_embeddings`；
- `signal-text-v1` input；
- pgvector exact recall。

新增 `GatewayEmbeddingProvider`：

```text
M3-B EmbeddingService
→ existing EmbeddingProvider
→ GatewayEmbeddingProvider
→ task_key=embedding
→ AIGateway
→ configured Provider / Model
```

Bridge 使用 primary route snapshot，并要求 Model config 显式声明与请求一致的 `embedding_version` 与 `dimensions`。这样不会让 fallback 静默改变 M3-B artifact 版本语义。

没有自动 backfill 全库，也没有 Migration 内调用 Provider。

## 9. Route / Versioning

业务只传 `task_key`。Route 决定：

- primary model；
- ordered fallback models；
- timeout；
- retry limit；
- budget policy；
- config；
- enabled。

每次修改 Route：

1. 锁定当前 active row；
2. 当前版本置 inactive；
3. 新建 `version + 1`；
4. 仅新 Invocation 使用新版本。

历史 Invocation 保存 `route_id + route_version + provider_key + model_name`，因此历史调用不会因当前 Route 修改而失去可解释性。

## 10. Retry / Fallback / Error Taxonomy

错误分类至少包含：

```text
AUTH_ERROR
RATE_LIMITED
TIMEOUT
NETWORK_ERROR
INVALID_REQUEST
MODEL_NOT_FOUND
CONTEXT_LENGTH_EXCEEDED
INVALID_RESPONSE
STRUCTURED_OUTPUT_INVALID
PROVIDER_UNAVAILABLE
BUDGET_EXCEEDED
UNKNOWN_PROVIDER_ERROR
```

另有 `CREDENTIAL_NOT_CONFIGURED`、`ROUTE_NOT_CONFIGURED` 等 Gateway 基础错误。

Retry：

- route/provider 配置取较小值；
- hard cap = 3；
- timeout / temporary network / 429 / selected 5xx 等才可重试；
- auth / invalid request / model not found 不无限 retry；
- Retry-After 仅在配置最大等待时间内执行。

Fallback：

- 只走显式 fallback list；
- 每个 Provider attempt 都写 `ai_invocation_attempts`；
- 记录 `retry_index`、`fallback_index`、provider/model、error code；
- 不无痕切换模型。

Provider 429 不进入 MediaCrawler `PlatformRiskEvent`。

## 11. Structured Output

Gateway 提供通用 `generate_structured(...)`：

- 调用前检查 JSON Schema 合法性；
- Provider 输出必须解析为 JSON object；
- 使用 Draft 2020-12 validator 校验；
- missing field / wrong type / malformed JSON / refusal 都不能返回 success；
- schema repair/retry 受同一 bounded retry 约束；
- Gateway 不理解 EvidenceClaim 业务含义。

## 12. Invocation / Attempt / Audit

`ai_invocations` 保存逻辑调用，`ai_invocation_attempts` 保存每次 provider attempt。

可追溯字段包括：

- invocation UUID；
- task / route version；
- provider/model；
- capability/status；
- SHA-256 input hash；
- prompt/schema version；
- input/output/total tokens；
- estimated cost；
- latency；
- retry/fallback；
- provider request id；
- pricing snapshot；
- error code；
- optional subject type/id；
- sanitized metadata。

默认不保存完整 Prompt/body/vector，不保存 API Key / Authorization。

Provider/Model/Route/Budget 的管理员配置变更继续复用现有 `ConfigurationChangeLog + X-Actor-ID`；Invocation/Attempt 是独立调用级审计。

## 13. Pricing / Cost

价格来自 Model 配置，不硬编码在业务代码。

每次 Invocation / Attempt 固化：

- `pricing_version`；
- input/output/embedding price snapshot；
- 最终 `estimated_cost`。

历史 cost 不会被后续价格配置重算覆盖。

Provider 没有 usage 或模型没有价格时，cost 保持 unknown；不会伪造为 0。

## 14. AI Budget / 并发语义

AI Budget 与 CollectionBudget 分离，避免采集预算字段语义变形。

Scope：

```text
global
task
provider
```

支持：

- daily cost；
- monthly cost；
- daily tokens；
- unknown usage policy。

调用前 `reserve`，调用后 `settle`。同一 Budget 使用 PostgreSQL `FOR UPDATE` 锁；monthly 聚合也在 Budget 锁保护下读取，因此两个 Worker 不能同时读取同一余额后各自透支。

Unknown cost：

- 默认 `block`；
- 可配置 `allow_once`；
- `allow_once` 也通过原子 reservation + unknown usage counter 控制，不会因为 cost=NULL 就当 0 无限调用。

Provider 网络调用位于数据库事务之外。

## 15. Admin API

前缀：

```text
/api/v1/admin/ai
```

Provider：

- list / get / create / update；
- enable / disable；
- connection test。

Model：

- list / create / update；
- enable / disable。

Route：

- list / get；
- versioned update。

Budget：

- list / create / update。

Invocation：

- list / detail，只读。

继续复用既有 Admin Token / Actor 模式。

Connection Test：

- 输入极短受控文本；
- 只调用指定 Provider/Model；
- 不使用 Event 全文；
- 不 fallback 到 Fake；
- Invocation `test=true`；
- 记录 usage/cost；
- 无 credential 返回 `CREDENTIAL_NOT_CONFIGURED`；
- 只有真实 adapter 成功才把 Provider validation 置 `PASSED`。

## 16. Web

现有 React/Vite 工作台新增：

```text
AI Providers
AI Routes
AI Budgets
AI Invocations
```

Provider 页面同时管理 Model，展示：

- Provider 名称 / Key；
- type / enabled；
- credential configured；
- validation status；
- model count；
- recent invocation / error rate；
- connection test。

Route 页面显示 task / primary / fallback / timeout / retry / enabled / version；保存创建新版本。

Budget 页面管理 scope、daily/monthly cost、daily tokens、unknown usage policy。

Invocation 页面展示 time/task/provider/model/status/tokens/cost/latency/retry/fallback/error 与 Attempt 链，不展示完整 Prompt。

## 17. 工程测试范围

AI Provider/Gateway 测试全部离线，使用 `httpx.MockTransport` 或测试 adapter，不访问公网。

覆盖：

- Provider success；
- auth error；
- 429；
- timeout；
- network error；
- 5xx；
- malformed JSON；
- refusal；
- structured malformed/invalid/valid；
- usage exists / missing；
- retry boundary；
- fallback audit；
- duplicate Invocation idempotency；
- credential non-leak；
- Provider key unique；
- Route version history/concurrency；
- AI Budget concurrent reserve / settle；
- unknown cost conservative policy；
- M3-B Embedding bridge → `signal_embeddings`。

最终 exact-head CI 仍必须完成项目既有全量 Gate：Ruff、mypy、pytest、M3 targeted/evaluation/performance、Alembic full round-trip、Definition 双同步、Web lint/typecheck/test/build。

## 18. Production Provider Validation

```text
Production AI Provider Validation = NOT_TESTED
```

当前没有在 PR/CI 使用生产 API Key，也没有真实付费 Provider 调用。MockTransport/Fake 的成功只能证明工程 contract，不得写成 Provider VERIFIED/PASSED。

后续真实验证应由人工提供 credential，在受控 Provider connection test / M4 收口中执行；至少在 M4 总收口或 M5 最终验收前完成真实 AI Provider E2E 更安全。

## 19. 明确未开始

M4-A 没有实现：

- EvidenceClaim；
- claim verification；
- supporting / contradicting signal IDs；
- unknowns；
- emotion / information-gap / visual score；
- risk level / recommended format / TOP ranking；
- Event Card；
- Script / 口播稿；
- 标题 / 封面文案 / material package；
- M5；
- LLM event judge 自动接入 clustering。

因此当前最终状态继续是：

```text
M4-A AI Gateway COMPLETE
M4-B NOT STARTED
M4-C NOT STARTED
M4-D NOT STARTED
M4 Overall NOT COMPLETE
```
