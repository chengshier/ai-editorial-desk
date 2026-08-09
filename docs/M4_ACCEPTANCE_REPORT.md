# M4 Acceptance Report

## 1. 阶段状态

```text
M4-A AI Gateway：COMPLETE
M4-B Evidence / Claim：COMPLETE
M4-C Trend / Editorial Score：COMPLETE
M4-D Event Card / Draft：COMPLETE
M4 Overall Engineering：COMPLETE
Production AI Provider Validation：NOT_TESTED
M5：NOT STARTED
```

M4-A / M4-B / M4-C / M4-D 的 COMPLETE 均为工程完成口径。M4 Overall Engineering 已完成，不代表生产 Provider 已真实联网验证，也不改变 M2 Real Smoke / Real-world Validation 的独立状态。

M1-M3 状态继续保持：

```text
M1 Engineering COMPLETE
M2 Engineering COMPLETE
M2 Real Smoke Validation DEFERRED / NOT_TESTED
M2 Real-world Validation NOT COMPLETE
M3 Overall Engineering COMPLETE
```

M4-D 对应 PR #18 `feat: 完成 M4-D Event Card、Draft与阶段收口` 已人工 Squash merge；merge commit / 当前 M4 工程基线为 `1df654d471f5a21c667ddd27e3f9d1c89df1af86`。

## 2. M4-A：AI Gateway

状态：`COMPLETE`。

已冻结并继续复用：

- Provider / Model / Task Route；
- Retry / Fallback；
- Budget reservation / settle；
- structured schema validation；
- Invocation / Attempt；
- token / cost / latency audit；
- Production Provider Validation 独立状态。

M4-C Editorial Scoring 使用 `AIGateway.generate_structured(task_key="editorial_scoring")`；M4-D AI Draft 使用 `AIGateway.generate_structured(task_key="draft_generation")`。业务层不得直接绕过 Gateway 调用 Provider URL。

## 3. M4-B：Evidence / Claim

状态：`COMPLETE`。

M4-C 与 M4-D 继续消费以下 M4-B artifact：

- `EvidenceClaim`；
- `EvidenceClaimSource`；
- `EventUnknown`；
- Claim verification state；
- Claim source provenance。

Editorial Scoring 与 Draft Generation 均不得修改 Claim verification、创建伪造 Evidence、删除 Unknown 或修改 RawSignal。M4-D Draft 的事实表达必须通过 Claim citation chain 受控引用这些 artifact。

## 4. M4-C：Trend / Editorial Score

状态：`COMPLETE`。

### 4.1 Migration / Persistence

Migration：

```text
20260809_0012_m4c_trend_editorial_scoring
```

Down revision：`20260809_0011`。

新增：

- `event_trend_snapshots`
- `editorial_scoring_runs`
- `editorial_scores`
- `editorial_score_overrides`

0012 未修改 0001～0011。

### 4.2 EventTrendSnapshot

`event_trend_snapshots` 是 immutable / append-only derived artifact。

版本：`trend-calculation-v1`。

同一 Event / version / window / input hash 使用 PostgreSQL 唯一约束与 insert-on-conflict 实现幂等。

确定性可用：

- `signal_velocity = new_signal_count / window_hours`；
- distinct source count；
- distinct platform count；
- cross_source；
- cross_platform；
- update_value component。

明确不可用：

```text
interaction_velocity = NULL
reason = INTERACTION_NORMALIZATION_UNAVAILABLE

cn_gap = NULL
reason = GEOGRAPHY_CLASSIFICATION_UNAVAILABLE

semantic_novelty = NULL
reason = EVENT_SEMANTIC_NOVELTY_UNAVAILABLE

media_availability = unavailable
reason = MEDIA_CLASSIFICATION_UNAVAILABLE
```

NULL / unavailable 不等于 0。

### 4.3 Update Value

第一版只使用可观察数据：

```text
min(new_signal_count, 5) * 6
+ min(new_claim_count, 2) * 10
+ min(new_confirmed_or_investigating_claim_count, 2) * 15
+ min(new_official_response_signal_count, 1) * 10
+ min(correction_count, 1) * 10
```

结果范围 0..100，并在 `component_metrics` 保存原始组件与公式。

### 4.4 Editorial Score

Score 是版本化分析 artifact，不 update 覆盖旧结果。

七维统一为 `0..100 integer`：

- `emotion`
- `information_gap`
- `visual_value`
- `user_relevance`
- `discussion`
- `novelty`
- `extendability`

默认模板：

```text
score_template = general
score_template_version = score-template-general-v1
emotion = 20
information_gap = 15
visual_value = 15
user_relevance = 15
discussion = 15
novelty = 10
extendability = 10
```

Service version：`editorial-score-service-v1`。

`traffic_total` 由 Service 确定性重算：

```text
sum(dimension_score * weight) / 100
```

模型输出的 `traffic_total` 不被信任。

### 4.5 Scoring Run / Prompt / Schema

版本：

```text
prompt_version = editorial-scoring-v1
schema_version = editorial-score-schema-v1
scoring_version = editorial-score-service-v1
```

Scoring input 使用 Event + Trend Snapshot + Evidence/Unknown 摘要；不重新发送所有 RawSignal 正文，不发送 raw_payload、credential、Authorization、完整 comment dump 或 embedding vector。

Source-derived 内容被明确标记为 untrusted data，不能成为 Prompt 指令。

### 4.6 Risk / Recommended Format

Risk level：`R0 / R1 / R2 / R3 / R4`。

AI 只产生 risk candidate。Consistency guard 至少执行：

- 无 Evidence → AI 不得 R0；
- 无 confirmed Claim → AI 不得 R0；
- 全部 Claim 为 single_source/disputed → AI 不得 R0；
- 仍有 open Unknown → AI 不得 R0。

R4 表示当前推荐表达路径存在高风险，不删除 Event；已证伪内容可作为 `fact_check` 主题。

有限 recommended format：

- `daily_compilation`
- `quick_explainer`
- `fact_check`
- `deep_dive`
- `entertainment`
- `consumer_safety`

### 4.7 Human Manual Score / Override

Human Score：

- `source_type=human`；
- Actor + reason；
- 完整七维；
- 不创建 Fake AI Invocation；
- AuditLog。

Human Override：

- append-only；
- 覆盖七维 / risk / recommended format；
- Actor + reason；
- 原始 Score 保留；
- Effective view 重算 total；
- 后续 AI rerun 新建 Score，但不能 silent overwrite Human override。

### 4.8 Preview / Apply / Provider Failure

Preview：

- 可产生真实 Invocation / token / cost / budget usage；
- 不写正式 EditorialScore。

Apply：

1. 短事务读取安全 snapshot；
2. 结束事务；
3. AIGateway structured call；
4. Service / risk 校验；
5. 新短事务重新确认 Event active；
6. 保存 Run / Score。

Provider / route / budget / schema 失败必须显式失败；不得 fallback 到 test Fake 后伪造生产 AI Score。Human manual score 不依赖 Provider。

### 4.9 Merged Event

当 `merged_into_event_id != NULL`：

- 禁止 source Event 新建 Trend；
- 禁止新建 Score；
- 禁止新建 Override；
- 返回 `EVENT_MERGED + target_event_id`；
- 历史 Trend / Score 仍可读取。

M4-C 不自动修改 Event.status，也不修改 M3 membership/cluster。

## 5. M4-D：Event Card / Editorial Pack / Draft

状态：`COMPLETE`。

### 5.1 Migration / Persistence

Migration：

```text
20260809_0013_m4d_editorial_pack_drafts
```

Revision ID：`20260809_0013`。

Down revision：`20260809_0012`。

新增：

- `event_cards`
- `editorial_packs`
- `draft_generation_runs`
- `editorial_drafts`
- `draft_claim_references`

0013 未修改 0001～0012。历史 FK 使用 RESTRICT 保护 Event / Trend / Editorial Score / AI Invocation / Draft chain / Claim provenance，不依赖 cascade 删除历史编辑 artifact。

### 5.2 Event Card

版本：`event-card-v1`。

Event Card 是 M4-D 的第一层确定性 artifact，核心语义：

- versioned；
- append-only；
- 输入幂等，唯一语义基于 `event_id + card_version + input_hash`；
- 保存 `evidence_snapshot_hash`；
- 绑定目标 Event 的 Trend Snapshot（可选）与 Effective Editorial Assessment；
- 保存当前 risk level / recommended format；
- 保存 confirmed / investigating / single_source / disputed / false Claim ID 分组与 open Unknown；
- v1 `generated_by=deterministic`，不为资料卡排版调用 AI；
- `ai_invocation_id` 在 deterministic v1 为 NULL；
- Evidence、Effective Score 或 Human Override 变化后，旧 Card 保留历史但视为 stale，不继续作为当前 Pack/Draft 输入。

Event Card provenance 链：

```text
Event
+ Evidence snapshot
+ Trend Snapshot
+ Effective Editorial Assessment
→ event-card-v1
```

### 5.3 Editorial Pack

版本：`editorial-pack-v1`。

Editorial Pack 以 Event Card 为直接上游，继续保持 versioned / append-only / input idempotent。

内容至少包括：

- source items；
- timeline items；
- Claim reference 摘要；
- open Unknown；
- suggested angles；
- material metadata；
- warnings。

Suggested angles v1 是 bounded deterministic helper，不是自动选题决策，也不建立 M5 Candidate ranking。

媒体安全语义：

- 只保留允许的 media metadata，例如 type / mime / duration / width / height；
- 保留 source URL 供人工核对；
- 不自动下载素材；
- 不输出 raw payload / Authorization / credential / secret；
- media metadata 缺失时显式记录 `MEDIA_METADATA_UNAVAILABLE`；
- `usage_note` 明确 metadata-only / no-download / rights-context manual review；
- disputed / false 相关素材保留额外风险提示。

Unavailable media 不得伪造为 available。

### 5.4 Draft Contract

版本：

```text
draft_service_version = draft-service-v1
prompt_version = draft-generation-v1
schema_version = draft-schema-v1
```

支持三种 draft type：

```text
short_30s
standard_90s
deep_180s
```

对应目标时长为 30 / 90 / 180 秒，并有 bounded hard character limits。

AI Draft 唯一路径：

```text
DraftGenerationInputBuilder
→ AIGateway.generate_structured(task_key="draft_generation")
→ Route / Budget / Retry / Fallback
→ Structured Schema Validation
→ Invocation / Attempt / Usage / Cost
→ Draft candidate validation
→ stale / risk / evidence revalidation
→ versioned EditorialDraft
```

### 5.5 Claim Citation Chain / Evidence-aware Generation

M4-D 冻结的事实引用边界：

- confirmed Claim：允许 `fact` 或 attributed；
- investigating Claim：必须 attributed；
- single_source Claim：必须 attributed，不得表达为 confirmed；
- disputed Claim：必须保留 dispute，并使用 disputed citation usage；
- false Claim：只能用于 debunk / fact-check，并使用 debunked citation usage；
- Unknown：只能出现在 open question section，不得作为事实答案。

每个 factual section 必须有至少一个 supplied Claim citation。Open-question section 必须只引用 open Unknown。

必须拒绝：

- 不存在于目标 Event 的 Claim；
- 跨 Event Claim / Unknown；
- Provider 虚构的 Claim / Unknown ID；
- 不符合当前 verification state 的 citation usage；
- unsupported factual section；
- false / disputed / single-source 被提升成无条件事实；
- Unknown 被改写成确定答案。

AI Draft 不能提升、确认、证伪或修改 Claim verification，也不能修改 Event membership、Trend、Editorial Score 或 Risk。

### 5.6 Risk-aware Generation

Draft Apply 使用 Effective Editorial Assessment 的 risk level：

- R4：只允许 `fact_check` AI Draft Apply；Event 不删除；
- R3：`fact_check` / `quick_explainer` 之外的普通路径必须有 Human 明确 `risk_approval_reason`；
- R0-R2：仍受 Evidence / citation / stale validation，不因风险较低而放松事实链；
- Preview 不写正式 Draft，但仍执行结构与 Evidence permission 校验。

Risk Gate 是生产业务语义，不通过测试配置、Mock Provider 或文档状态绕过。

### 5.7 Human Draft

Human Draft 已完成：

- Actor required；
- reason required；
- 至少一个合法 Claim reference；
- `source_type=human`；
- 不创建 Fake AI Invocation；
- 形成独立 `draft_chain_id`；
- 初始 `draft_version=1`；
- 写 AuditLog。

Human Draft 同样受 Event merge / Claim verification / reference permission 约束。

### 5.8 Human Revision / Version Chain

Human Revision 已完成：

- append-only；
- 只能基于当前 chain 最新版本创建下一版本；
- `parent_draft_id` 指向上一版本；
- `draft_chain_id` 保持不变；
- `draft_version` 单调递增；
- `(draft_chain_id, draft_version)` 数据库唯一；
- Actor + `change_note`；
- 新版本重新保存当前合法 Claim references；
- 写 AuditLog。

AI 原始 Draft 不被 update 覆盖。Human Revision 创建新的 `source_type=human` 版本，AI/Human 历史均可审计。

### 5.9 Stale Editorial Context Protection

Draft Generation 在 Provider 调用前建立 snapshot，Apply 阶段重新读取并锁定当前 Event editorial context。

以下变化必须阻止旧 snapshot 落正式 Draft：

- Evidence snapshot 变化；
- Event 状态 / membership context 变化；
- Effective Editorial Assessment 变化；
- Human Override 变化；
- Claim verification 变化导致 citation usage 失效；
- Unknown 已 resolved / dismissed；
- Event 已 merged。

对应错误使用显式 stale / merged 语义，不允许静默落旧稿。

### 5.10 Merged Event Protection

source Event 已存在 `merged_into_event_id` 时：

- 禁止新建 Event Card；
- 禁止新建 Editorial Pack；
- 禁止生成新 Draft；
- 禁止新建 Human Revision；
- 返回 `EVENT_MERGED + target_event_id`；
- 已存在历史 Card / Pack / Draft 仍可读取。

M4-D 不删除 source Event，也不修改 M3 clustering 语义。

### 5.11 Transaction Boundary

AI Provider 调用位于数据库长事务之外：

1. 短事务构建 DraftGenerationSnapshot；
2. 结束读取事务；
3. AIGateway Provider call；
4. candidate / Evidence / Risk validation；
5. 新短事务重新锁定并验证当前 context；
6. 保存 Draft / citation / run 状态。

不得为了规避 stale context 而把 Provider 网络调用包进长数据库事务。

### 5.12 Markdown Export

`EditorialMarkdownExporter` 是 pure deterministic renderer：

- 读取已存在的 Event Card / Editorial Pack / 可选 Draft；
- 输出 Event、Summary、Trend、Editorial Score、Risk、Claims、Unknowns、Timeline、Sources、Suggested Angles、Material Checklist、Draft；
- Claim references 显式保留 claim_id / usage；
- 不再次调用 AI；
- 不创建新的 Invocation；
- 不修改 artifact；
- 不输出 raw payload、credential、Authorization 或受控 secret。

### 5.13 M4-D Scope Boundary

M4-D 明确不包含：

- DailyCandidate / 今日候选池；
- 采用 / 观察 / 放弃工作流；
- Publication；
- Performance Feedback；
- 自动调权；
- M5 Editorial Workbench。

以上均未作为 M4-D 工程完成条件，也未在 PR #18 中进入实现范围。

## 6. Admin API

M4-C：

```text
GET  /api/v1/admin/events/{event_id}/trend
POST /api/v1/admin/events/{event_id}/trend/calculate
GET  /api/v1/admin/events/{event_id}/editorial-scores
GET  /api/v1/admin/events/{event_id}/editorial-scores/effective
POST /api/v1/admin/events/{event_id}/editorial-scores/preview
POST /api/v1/admin/events/{event_id}/editorial-scores
POST /api/v1/admin/events/{event_id}/editorial-scores/manual
POST /api/v1/admin/events/{event_id}/editorial-scores/{score_id}/override
```

M4-D：

```text
GET  /api/v1/admin/events/{event_id}/cards
POST /api/v1/admin/events/{event_id}/cards
GET  /api/v1/admin/events/{event_id}/editorial-packs
POST /api/v1/admin/events/{event_id}/editorial-packs
GET  /api/v1/admin/events/{event_id}/drafts
GET  /api/v1/admin/events/{event_id}/drafts/{draft_id}
POST /api/v1/admin/events/{event_id}/drafts/preview
POST /api/v1/admin/events/{event_id}/drafts
POST /api/v1/admin/events/{event_id}/drafts/manual
POST /api/v1/admin/events/{event_id}/drafts/{draft_id}/revisions
GET  /api/v1/admin/events/{event_id}/editorial-pack/export.md
```

所有写操作要求 Admin Token + `X-Actor-ID`。API 不返回 raw_payload、credential、Authorization、完整 Prompt 或 vector。

## 7. 测试与回归

M4-D 新增覆盖至少包括：

- Event Card deterministic / idempotent；
- Editorial Pack deterministic / material metadata safety；
- AI Draft 三种时长；
- Claim citation chain；
- unsupported / cross-event Claim / Unknown 拒绝；
- false / disputed / single_source / investigating permission；
- Risk-aware R3 / R4 generation；
- Human Draft；
- Human Revision / monotonic version chain；
- AI 原始稿不可覆盖；
- Draft concurrent apply；
- concurrent revision chain uniqueness；
- stale Evidence / Effective Assessment / Unknown protection；
- merged Event protection；
- Provider route / budget / schema / unavailable failures；
- Markdown export deterministic / no-secret；
- migration 0013 / downgrade isolation；
- Admin API auth / actor / safe output。

PR #18 final exact-head：

```text
head = 9ae6033b57111a800c24c3eb69aa6ef694e53235
GitHub Actions run id = 31312854489
run number = 383
status = completed
conclusion = success
```

Python + Web 均 success。Final exact-head CI 包含：

- Ruff；
- mypy；
- M3 concurrent regression；
- full pytest：`489 passed, 1 warning`；
- M3 offline engineering evaluation；
- M3 performance baseline；
- Alembic five-step round trip；
- connector definition sync ×2；
- Web lint / typecheck / unit test / production build。

所有 AI 测试使用离线 Mock/Fake/MockTransport，未调用真实付费 Provider。

## 8. final_review

```text
final_review = DEFERRED
```

M4 工程验收已完成；最终内容编辑质量、真实账号运营效果、生产模型输出质量与上线前人工审稿不由离线工程 Gate 自动判定，继续保持 `DEFERRED`。

## 9. Production Provider Validation

```text
Production AI Provider Validation = NOT_TESTED
```

M4 Overall Engineering COMPLETE 不要求真实付费 Provider 验证。CI Fake/Mock 成功不能把该状态改成 PASSED / VERIFIED。只有后续人工提供生产 credential 并完成真实网络调用，才能单独更新该状态。

## 10. M4 Overall Engineering

```text
M4 Overall Engineering = COMPLETE
```

完成范围：

```text
M4-A AI Gateway
→ M4-B Evidence / Claim
→ M4-C Trend / Editorial Score
→ M4-D Event Card / Editorial Pack / Draft / Human Revision / Markdown Export
```

M4 COMPLETE 是工程阶段闭环，不改变：

```text
M2 Real Smoke Validation = DEFERRED / NOT_TESTED
M2 Real-world Validation = NOT COMPLETE
Production AI Provider Validation = NOT_TESTED
final_review = DEFERRED
```

## 11. M5

```text
M5 = NOT STARTED
```

下一阶段为 M5-A，但本报告不定义或启动 M5 功能。开始 M5-A 时必须从当时最新 `main` 新建独立分支，不得从 `feature/m4d-editorial-pack` 或任何旧 M4 feature 分支派生。