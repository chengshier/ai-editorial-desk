# AI 编辑部项目开发入口

## 当前阶段

```text
M1 COMPLETE / 已合并
M2 Engineering COMPLETE / 已合并
M2 Real Smoke Validation DEFERRED / NOT_TESTED
M2 Real-world Validation NOT COMPLETE
M3 Overall Engineering COMPLETE / 已合并
M4-A AI Gateway COMPLETE / PR #15 已合并
M4-B Evidence / Claim COMPLETE / PR #16 Open
Production AI Provider Validation NOT_TESTED
M4-C NOT STARTED
M4-D NOT STARTED
M4 Overall NOT COMPLETE
M5 NOT STARTED
```

当前分支：

```text
feature/m4b-evidence-claims
```

当前 PR：

```text
#16 feat: 完成 M4-B Evidence与Claim证据链基础
```

PR #16 保持 Open，不自行合并。M4-C 只有在 PR #16 人工合并后，才能从最新 `main` 创建新的独立分支；不得从 `feature/m4b-evidence-claims` 继续派生。

M2 Real Smoke Deferred 状态继续保留。进入 M4 Engineering 不等于微博/B站/知乎真实 Smoke 已验证。Production AI Provider Validation 同理：CI Fake/Mock 通过不等于生产 Provider 已真实验证。

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

## 当前正式处理链

```text
RawSignal
→ Event / EventSignal                                  M3-A
→ EmbeddingInput(signal-text-v1)
→ versioned signal_embeddings
→ pgvector exact cosine recall                         M3-B
→ deterministic fingerprint / exact-near duplicate
→ event-match-v1 / Event assignment / Merge / Split    M3-C
→ offline evaluation / convergence / provenance
→ bounded dry-run-first reprocessing                   M3-D

Business Task
→ AI Task Route / immutable version
→ Provider / Model
→ AIGateway
→ Invocation / Attempt
→ Usage / Cost / Audit
→ AI Budget reserve / settle                           M4-A

Event + EventSignal / RawSignal
→ EvidenceInputBuilder
→ AIGateway.generate_structured(task=evidence_extraction)
→ Evidence business validation
→ EvidenceClaim + supporting/contradicting Source FK
→ EventUnknown
→ Human verification                                   M4-B
```

Connector / CollectorRuntime 仍停在 RawSignal 边界。M4-A/M4-B 均不修改 M3 clustering、evaluation ground truth 或 threshold。

## M4-A 基础

Migration：

```text
20260809_0010_m4a_ai_gateway
```

正式基础表：

```text
ai_providers
ai_models
ai_task_routes
ai_invocations
ai_invocation_attempts
ai_budgets
ai_budget_usages
```

核心原则：

- 业务只引用 `task_key`，不硬编码 Provider URL / provider_key / 商业模型名；
- credential 只保存 opaque `credential_ref`；当前 resolver 使用受控 `env://NAME`；
- `AIGateway.embed / generate_text / generate_structured` 是统一 AI 调用入口；
- OpenAI-compatible adapter 配置化，支持显式 cloud/local compatible endpoint；
- Route 每次变更创建新 version，历史 Invocation 不被当前配置覆盖；
- bounded retry / explicit fallback 每个 Attempt 可审计；
- pricing snapshot / estimated cost 固化到历史 Invocation；
- AI Budget 与 CollectionBudget 分离，PostgreSQL 锁保护 reserve/settle；
- M3-B `EmbeddingProvider` 通过 `GatewayEmbeddingProvider` 桥接，不重建 SignalEmbedding/InputBuilder/Vector Recall；
- CI AI tests 只用 Fake/MockTransport。

0010 已注册以下 route v1，默认全部 disabled：

```text
embedding
event_boundary_review
evidence_extraction
editorial_scoring
draft_generation
final_review
```

## M4-B Evidence 数据基础

Migration head：

```text
20260809_0011_m4b_evidence_claims
```

新增：

```text
evidence_extraction_runs
evidence_claims
evidence_claim_sources
event_unknowns
```

### EvidenceClaim

Claim type：

```text
fact
allegation
opinion
forecast
```

Verification state：

```text
confirmed
investigating
single_source
disputed
false
```

AI 只可产生候选，并由 Service 推导 `single_source / investigating / disputed`。AI 无权自动写 `confirmed / false`；模型 confidence 只保存为 `extraction_confidence`，不等于事实真实性。

Claim 使用 stable fingerprint：

```text
SHA-256(claim_type + normalized claim_text)
UNIQUE(event_id, claim_fingerprint)
```

### Evidence Source

Evidence source 使用真实 FK 关联表，而不是裸 UUID 数组：

```text
claim_id -> evidence_claims.id
signal_id -> raw_signals.id
role      -> supporting | contradicting
```

`UNIQUE(claim_id, signal_id)` 保证同一 Signal 不能同时扮演两个 role；Signal 必须通过 EventSignal 属于目标 Event。RawSignal FK 使用 `ON DELETE RESTRICT`，防止历史证据静默丢失。

### Unknown

Unknown 是一等业务对象，不伪装成 Claim：

```text
status      = open | resolved | dismissed
source_type = ai | human
```

Unknown fingerprint 在 Event 内唯一；AI rerun 不自动重新打开已经 resolved/dismissed 的 Unknown。

## Evidence Input / Prompt 安全

`EvidenceInputBuilder` 默认只把以下安全字段送入 Provider：

- signal ID；
- title / text；
- author name；
- platform；
- published / collected time；
- original/canonical URL metadata。

明确排除：

- `raw_payload`；
- credential / Cookie / Authorization；
- connector/account config；
-完整 comment dump；
- Embedding vector。

输入按 effective time + signal ID 稳定排序，并由 `max_signals / max_chars_per_signal / max_total_chars` 限制。截断会记录 `truncated` 与 signal IDs，不保存完整被截文本。

Prompt / Schema：

```text
prompt_version = evidence-extraction-v1
schema_version = evidence-schema-v1
extraction_version = evidence-service-v1
```

Signal 文本被明确标记为 `UNTRUSTED CONTENT`。Prompt 告诉模型不得执行正文指令、不得编造 source ID、不得自行确认事实；Service 仍进行 Event/source/confidence/verification 权限二次校验。因此 prompt injection 防御不依赖模型自觉。

## Evidence Extraction 调用链

```text
短事务读取 Event + safe Signal snapshot
→ 关闭事务
→ AIGateway.generate_structured(task=evidence_extraction)
→ Route / Budget / Retry / Fallback / Schema / Invocation / Cost
→ Evidence business validation
→ 新短事务重新检查 Event 未 merged + signal membership
→ apply Claim / Source / Unknown + Audit
```

Invocation 固定关联：

```text
task_key=evidence_extraction
subject_type=event
subject_id=<event UUID>
prompt_version=evidence-extraction-v1
schema_version=evidence-schema-v1
```

Provider 网络等待不持有 Event 长事务锁。

## Preview / Partial

Preview 会正常走 Gateway，因此未来真实 Provider 下可能产生费用；它会写 Invocation / ExtractionRun，但不写 Claim / Unknown 业务状态。

Apply 的局部脏结果采用 `PARTIAL`：合法项保存，无来源 Claim 不落库并记录 `UNSUPPORTED_CLAIM`，不存在/不属于 Event 的 signal ID 记录 invalid item。ExtractionRun / API / Audit 保留 invalid count 和安全错误码，不把局部错误静默包装成 success。

## Human Verification

人工 Claim 不依赖 AI Provider：

- Admin Token + `X-Actor-ID`；
- claim text/type；
- 至少一个真实 Event source；
- AuditLog；
- `ai_invocation_id = NULL`。

人工 verification：

- `confirmed` 至少一个 supporting source + reason；
- `false` 至少一个 contradicting source + reason；
- 两个来源不会自动等于 confirmed；
- confirmed Claim 不能删除最后一个 supporting source；
- false Claim 不能删除最后一个 contradicting source；
- Human verification/editor note 不被 AI rerun 覆盖。

如果 Event 已 merged：

```text
EVENT_MERGED
+ target_event_id
```

source Event 不允许新增/修改 Evidence。

## Evidence Admin API

路径沿用现有 `/api/v1/admin/events`：

```text
GET    /{event_id}/evidence
POST   /{event_id}/evidence/extract
POST   /{event_id}/claims
GET    /{event_id}/claims
GET    /{event_id}/claims/{claim_id}
PATCH  /{event_id}/claims/{claim_id}
POST   /{event_id}/claims/{claim_id}/sources
DELETE /{event_id}/claims/{claim_id}/sources/{signal_id}
POST   /{event_id}/claims/{claim_id}/verify
GET    /{event_id}/unknowns
POST   /{event_id}/unknowns
PATCH  /{event_id}/unknowns/{unknown_id}
```

Safe Evidence view 不返回 RawSignal full text、raw_payload、API Key、Authorization、完整 Prompt 或 Embedding vector。

## Production Provider Validation

```text
Production AI Provider Validation = NOT_TESTED
```

M4-B 没有使用生产 API Key 或真实付费 Provider 网络调用。CI MockTransport/Fake 只能证明 Engineering Contract，不能替代生产 Validation。

人工 Claim/Verification 流程在 Provider NOT_TESTED 时仍然可用。

## CI Gate

PR #16 只在最新 exact-head 同时满足以下条件时具备人工合并资格：

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

所有 AI tests 必须离线。

## M4-B 完成语义

`M4-B Evidence / Claim COMPLETE` 表示 Evidence Claim、真实 Signal provenance、Unknown、ExtractionRun/Invocation provenance、bounded input、Prompt/Schema version、AI/Human verification 权限边界、Preview/PARTIAL、Admin API 与 PostgreSQL/离线 AI 回归已经形成工程闭环。

它不表示：

- Production AI Provider 已真实验证；
- 系统已经具备“自动判断新闻真伪”的能力；
- Source Credibility 评分已实现；
- Trend / Editorial Score 已实现；
- Event Card / Script / Draft 已实现；
- M4 Overall 已完成；
- M5 已开始。
