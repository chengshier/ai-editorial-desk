# AI Editorial Desk

AI 编辑部系统：面向短视频创作者的多来源信息发现、资料整理、编辑判断与内容生产辅助系统。

**当前工程状态：M1 COMPLETE；M2 Engineering COMPLETE；M2 Real Smoke Validation = DEFERRED / NOT_TESTED；M2 Real-world Validation = NOT COMPLETE；M3 Overall Engineering COMPLETE；M4-A AI Gateway COMPLETE；M4-B Evidence / Claim COMPLETE；M4 Overall NOT COMPLETE。**

> PR #15 已合并到 `main`。M4-B 当前位于 PR #16 `feature/m4b-evidence-claims`，PR 保持 Open，不自行合并。Production AI Provider Validation 继续 `NOT_TESTED`；CI Fake/Mock 不能替代真实 Provider Validation。

开发入口见 [`docs/START_HERE.md`](docs/START_HERE.md)，M4 工程验收见 [`docs/M4_ACCEPTANCE_REPORT.md`](docs/M4_ACCEPTANCE_REPORT.md)，M3 工程验收见 [`docs/M3_ACCEPTANCE_REPORT.md`](docs/M3_ACCEPTANCE_REPORT.md)，架构决定见 [`docs/DECISIONS.md`](docs/DECISIONS.md)。

## 当前处理链

```text
Connector Definition / Source / Schedule
→ CollectionTask / CollectorRuntime
→ Budget + Risk Guard + Run
→ RSS / Manual URL / Hotlist / MediaCrawler Adapter
→ Platform Mapper
→ RawSignal / RawSignalComment
→ Checkpoint / Incremental / Resume

RawSignal
→ Event / EventSignal                                      M3-A
→ EmbeddingInput(signal-text-v1) / versioned Embedding     M3-B
→ pgvector exact cosine candidate recall                   M3-B
→ deterministic fingerprint / exact + near duplicate       M3-C
→ event-match-v1 / Event assignment / Merge / Split        M3-C
→ offline evaluation / convergence / bounded reprocessing  M3-D
→ processing + assignment provenance                       M3-D

Business Task
→ AI Task Route / immutable route version                  M4-A
→ Provider / Model target                                  M4-A
→ AIGateway                                                M4-A
→ Invocation / Attempt audit                               M4-A
→ Usage / pricing snapshot / estimated cost                M4-A
→ AI Budget reserve / settle                               M4-A

Event + EventSignal / RawSignal
→ EvidenceInputBuilder                                     M4-B
→ AIGateway.generate_structured(evidence_extraction)       M4-B
→ Evidence business validation                             M4-B
→ EvidenceClaim + Claim Source FK                          M4-B
→ EventUnknown                                             M4-B
→ Human verification                                       M4-B
```

采集层、M3 Processing、M4 AI 基础和 Evidence 层继续解耦。M4-B 不修改 M3 clustering、evaluation ground truth 或 threshold，也不把 AI 输出直接当成“已确认事实”。

## M4-A — AI Gateway / Provider / Route / Cost Governance

M4-A 已建立：

- `ai_providers` / `ai_models` / versioned `ai_task_routes`；
- opaque `credential_ref` 与受控 resolver；
- `AIGateway.embed / generate_text / generate_structured`；
- OpenAI-compatible production adapter；
- bounded retry / explicit fallback；
- `ai_invocations` / `ai_invocation_attempts`；
- token usage / pricing snapshot / estimated cost；
- 独立 AI Budget + PostgreSQL reserve/settle concurrency gate；
- Provider/Route/Budget/Invocation Admin API 与 Web；
- M3-B `GatewayEmbeddingProvider` bridge；
- CI 全部离线，不访问真实付费 Provider。

Migration：

```text
20260809_0010_m4a_ai_gateway
```

## M4-B — Evidence / Claim / Unknowns

M4-B 建立“这件事目前有哪些可追溯事实候选、争议和未知项”，不自动做新闻真假裁判。

Migration：

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

### Claim 与来源证据链

`EvidenceClaim`：

- `claim_type = fact / allegation / opinion / forecast`；
- `verification_state = confirmed / investigating / single_source / disputed / false`；
- nullable `extraction_confidence`；
- stable SHA-256 `claim_fingerprint`；
- ExtractionRun / Invocation provenance；
- `created_by_type = ai / human`；
- actor / editor note / timestamps。

同 Event 使用：

```text
UNIQUE(event_id, claim_fingerprint)
```

Evidence source 使用真实 FK 关联表：

```text
claim_id -> evidence_claims.id
signal_id -> raw_signals.id
role      -> supporting | contradicting
UNIQUE(claim_id, signal_id)
```

RawSignal FK 使用 `ON DELETE RESTRICT`，防止历史证据静默丢失。所有 source 必须通过 EventSignal 属于目标 Event。

### AI 与 Human 权限

AI structured output 只是候选：

```text
有 contradicting evidence -> disputed
仅 1 个 supporting        -> single_source
多个 supporting           -> investigating
```

AI 无权自动写：

```text
confirmed
false
```

即使模型输出这两个状态，Service 也不会采信。

Human verification 必须带 Actor + reason：

- confirmed 至少 1 supporting source；
- false 至少 1 contradicting source；
- 两个来源不自动等于 confirmed；
- confirmed Claim 不能删除最后一个 support；
- false Claim 不能删除最后一个 contradiction；
- Human verification/editor note 不被 AI rerun 覆盖。

### Unknown

Unknown 是独立业务对象：

```text
status      = open | resolved | dismissed
source_type = ai | human
```

同 Event 使用 stable fingerprint 幂等；AI rerun 不自动重新打开已 resolved/dismissed Unknown。

### Evidence Input / Prompt 安全

Provider 输入仅来自 Event + EventSignal + 安全 RawSignal 字段：

- signal ID；
- title / text；
- author / platform；
- published / collected time；
- original/canonical URL metadata。

默认不输入：

- `raw_payload`；
- credential / Cookie / Authorization；
- connector config；
-完整 comment dump；
- Embedding vector。

输入有 deterministic order 与 `max_signals / max_chars_per_signal / max_total_chars` hard bound。截断显式记录，不无声吞掉。

版本：

```text
prompt_version = evidence-extraction-v1
schema_version = evidence-schema-v1
extraction_version = evidence-service-v1
```

RawSignal 文本被标记为 `UNTRUSTED CONTENT`；Prompt 防注入之外，Service 仍强制检查 Event membership、source role、confidence 与 AI verification 权限。

### Extraction / Preview / Partial

AI extraction 严格复用 M4-A：

```text
EvidenceInputBuilder
→ AIGateway.generate_structured(task=evidence_extraction)
→ Route / Budget / Retry / Fallback / Schema
→ Invocation / Attempt / Cost
→ Evidence Service business validation
→ short transaction apply
```

Provider 网络调用不持有 Event 长事务。

Preview：产生 Invocation/ExtractionRun，但不写 Claim/Unknown；真实 Provider 下不宣称免费。

Apply 对局部脏输出使用 `PARTIAL`：合法项保存，无来源 Claim 记录 `UNSUPPORTED_CLAIM` 而不落事实表，错误 signal ID 记录 invalid item，Run/API/Audit 保留 invalid count 与安全错误码。

### Merged Event

如果：

```text
event.merged_into_event_id != NULL
```

旧 source Event 禁止新增/修改 Evidence，返回：

```text
EVENT_MERGED
+ target_event_id
```

历史 Evidence 仍可读取。

## Evidence Admin API

沿用 `/api/v1/admin/events`：

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

## CI Gate

```bash
ruff check .
mypy apps packages
pytest
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

所有 AI Provider / Evidence extraction CI 测试必须离线。

## 当前阶段边界

```text
M1 COMPLETE
M2 Engineering COMPLETE
M2 Real Smoke Validation DEFERRED / NOT_TESTED
M2 Real-world Validation NOT COMPLETE
M3 Overall Engineering COMPLETE
M4-A AI Gateway COMPLETE / PR #15 merged
M4-B Evidence / Claim COMPLETE / PR #16 Open
Production AI Provider Validation NOT_TESTED
M4-C NOT STARTED
M4-D NOT STARTED
M4 Overall NOT COMPLETE
M5 NOT STARTED
```

PR #16 保持 Open，由人工决定是否合并。后续 M4-C 只有在 PR #16 人工合并后才能从最新 `main` 创建独立分支，不得从 `feature/m4b-evidence-claims` 继续派生。
