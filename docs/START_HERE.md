# AI 编辑部项目开发入口

## 当前阶段

```text
M1 Engineering COMPLETE / 已合并
M2 Engineering COMPLETE / 已合并
M2 Real Smoke Validation DEFERRED / NOT_TESTED
M2 Real-world Validation NOT COMPLETE
M3 Overall Engineering COMPLETE / 已合并
M4-A AI Gateway COMPLETE / 已合并
M4-B Evidence / Claim COMPLETE / 已合并
M4-C Trend / Editorial Score COMPLETE / 已合并
M4-D Event Card / Draft COMPLETE / PR #18 MERGED
M4 Overall Engineering COMPLETE
Production AI Provider Validation NOT_TESTED
M5 NOT STARTED
```

M4-D 已通过 PR #18 `feat: 完成 M4-D Event Card、Draft与阶段收口` 人工 Squash merge 到 `main`。M4 工程阶段已经收口，但 Production AI Provider Validation 仍为 `NOT_TESTED`，M2 Real Smoke / Real-world Validation 状态保持不变。

当前没有 M5 功能开发分支。下一开发阶段是 M5-A；开始时必须以**当时最新 `main`** 为基线新建独立分支，不得从 `feature/m4d-editorial-pack`、`feature/m4c-trend-editorial-scoring` 或任何旧 feature 分支派生。

## 开发前必读

1. `docs/AI编辑部_综合开发实施规划_V1.2.md`
2. `docs/AI编辑部_技术开发文档_V1.2.md`
3. `docs/AI编辑部_PRD_V1.2.md`
4. `docs/DECISIONS.md`
5. `docs/M4_ACCEPTANCE_REPORT.md`
6. `docs/M3_ACCEPTANCE_REPORT.md`
7. `docs/CHANGELOG.md`

## 已完成处理链

```text
Connector Definition / Source / Schedule
→ CollectionTask / CollectorRuntime
→ RawSignal / RawSignalComment
→ Event / EventSignal
→ Signal Embedding / Matching / Clustering
→ EvidenceClaim / EvidenceClaimSource / EventUnknown
→ EventTrendSnapshot
→ EditorialScoringInputBuilder
→ AIGateway editorial_scoring
→ EditorialScoringRun / EditorialScore
→ Risk Consistency Guard
→ Human Manual Score / Override
→ Effective Editorial Assessment
→ Event Card
→ Editorial Pack
→ Draft Generation
→ Human Draft / Human Revision
→ Markdown Export
```

## M4-C 冻结语义

### Trend != Editorial Score

Trend 回答：事件是否正在发酵。

Editorial Score 回答：事件对账号是否值得讲。

M4-C 不把规则/趋势特征和 AI 语义评分混成一个最终黑箱，也不建立 DailyCandidate/TOP5/TOP10/TOP20。

### Trend Snapshot

版本：`trend-calculation-v1`。

`event_trend_snapshots` 是 append-only、版本化、可幂等重算的派生 artifact。计算使用显式 UTC window；unavailable 与数值 `0` 必须区分。

当前明确保持 unavailable 的能力：

- interaction velocity：`INTERACTION_NORMALIZATION_UNAVAILABLE`；
- cn_gap：`GEOGRAPHY_CLASSIFICATION_UNAVAILABLE`；
- semantic novelty：`EVENT_SEMANTIC_NOVELTY_UNAVAILABLE`；
- media availability：`MEDIA_CLASSIFICATION_UNAVAILABLE`。

禁止用平台名推断国内/海外，禁止把不同平台互动数直接相加，禁止为了 novelty 临时向 Event 写 centroid。

### Editorial Score / Human Priority

版本：

```text
score template: general
score template version: score-template-general-v1
scoring version: editorial-score-service-v1
prompt version: editorial-scoring-v1
schema version: editorial-score-schema-v1
```

七维统一 `0..100 integer`；`traffic_total = sum(dimension * weight) / 100`，由 Service 重算。模型返回的 total 不作为业务真相。

Scoring 只能读取 Claim verification / source count / Unknown 状态，不能创建、确认、删除或改写 Evidence。Human manual score 与 Human override 均保留独立 provenance；后续 AI rerun 可以产生新 Score，但不能 silent overwrite Human 决定。

## M4-D 冻结语义

### Artifact 分层

M4-D 明确保持三层：

```text
Event Card
→ Editorial Pack
→ Draft
```

Event Card 是当前 Event + Evidence + Trend + Effective Editorial Assessment 的确定性编辑快照；Editorial Pack 是基于 Card 整理出的资料包；Draft 是在 Card/Pack 与 Evidence permission 约束下生成或人工创建的版本化稿件。三者不得合并成一个不可审计的 AI 输出。

### Event Card

版本：`event-card-v1`。

- versioned / append-only；
- 通过 `event_id + card_version + input_hash` 保持输入幂等；
- 保存 Evidence snapshot provenance；
- 绑定 Trend Snapshot（可为空）与 Effective Editorial Assessment；
- 保存 risk / recommended format；
- v1 为 deterministic build，`ai_invocation_id = NULL`；
- Evidence、Effective Score 或 Human Override 变化后，旧 Card 继续保留为历史，但不能作为当前 Pack/Draft 的有效输入。

### Editorial Pack

版本：`editorial-pack-v1`。

- versioned / append-only / input idempotent；
- 包含 source items、timeline items、Claim reference 摘要、open Unknown、suggested angles；
- material 只保存受控 media metadata 与原始 source URL，不下载素材，不把 raw payload / Authorization / secret 带入 Pack；
- 媒体 metadata 不可用时使用显式 warning，例如 `MEDIA_METADATA_UNAVAILABLE`，不得伪造可用性；
- disputed / false / single-source Claim 对应资料必须保留风险提示。

### Draft Generation

版本：

```text
draft service: draft-service-v1
prompt version: draft-generation-v1
schema version: draft-schema-v1
```

支持：

```text
short_30s
standard_90s
deep_180s
```

AI Draft 只能通过：

```text
AIGateway.generate_structured(task_key="draft_generation")
```

完整经过 Route / Budget / Retry / Fallback / Schema / Invocation / Attempt / Usage / Cost。Provider 网络调用位于数据库长事务之外。

### Evidence / Citation 安全边界

Draft 中的事实只能沿目标 Event 内真实 Evidence Claim 引用：

- confirmed：可 `fact` 或 attributed；
- investigating：必须 attributed；
- single_source：必须 attributed，不能当 confirmed；
- disputed：必须保留 disputed 语义；
- false：只能用于 debunk / fact-check，不得重新作为事实传播；
- Unknown：只能作为 open question，不得转成事实答案。

每个 factual section 必须引用 Claim；unsupported / 跨 Event / verification 不允许的 Claim usage 必须拒绝。AI Draft 无权修改或提升 Claim verification，也不能创建虚构 Claim / Unknown / source。

### Risk-aware Draft Path

Draft Apply 继续使用 M4-C Effective Risk：

- R4：只允许 `fact_check` AI Draft Apply；Event 不因此删除；
- R3：普通内容路径需要 Human 明确 risk approval reason；
- Preview 不绕过 Evidence validation，但不会写正式 Draft；
- Risk Gate 不得通过配置、测试或文档被降级。

### Human Draft / Human Revision

Human Draft：

- Actor + reason；
- 必须有合法 Claim references；
- `source_type=human`；
- 不创建 Fake AI Invocation；
- 建立独立 draft chain v1。

Human Revision：

- 只能基于当前 chain 最新版本创建下一版本；
- append-only；
- 保留 parent / chain / version provenance；
- AI 原始稿不能被 Human Revision update 覆盖；
- Human Revision 形成新的版本记录并写 AuditLog。

### Stale / Merge / Transaction Protection

Draft 生成先构建安全 snapshot，再调用 Provider；Apply 阶段重新读取并锁定当前 Event context：

- Evidence snapshot 变化 → stale；
- Effective Editorial Assessment / Human Override 变化 → stale；
- Claim verification 变化导致 citation usage 不再合法 → stale；
- Unknown 不再 open → stale；
- source Event 已 merged → `EVENT_MERGED + target_event_id`，禁止新增 Card/Pack/Draft；
- 历史 artifact 继续可读。

不得为了消除 stale 检查而把 Provider 调用包进数据库长事务。

### Markdown Export

`EditorialMarkdownExporter` 是 deterministic renderer：

- 只读取已存在的 Event Card / Editorial Pack / 可选 Draft；
- 输出 Event / Trend / Editorial Score / Risk / Claims / Unknowns / Timeline / Sources / Suggested Angles / Material Checklist / Draft；
- 不再次调用 AI；
- 不修改 artifact；
- 不输出 raw payload、credential、Authorization 或未受控 secret。

### M4-D 明确不包含

- DailyCandidate / 今日候选池；
- 采用 / 观察 / 放弃工作流；
- Publication；
- Performance Feedback；
- 自动调权；
- M5 Editorial Workbench。

这些属于 M5 或更后阶段，M4-D 不提前实现。

## Production AI Provider Validation

```text
Production AI Provider Validation = NOT_TESTED
```

M4-A～M4-D 工程完成与 CI Mock/Fake 成功均不能把该状态改成 PASSED。只有后续人工提供真实 production credential 并完成明确的真实网络验证后，才能单独更新。

## Migration

当前 head：

```text
20260809_0013_m4d_editorial_pack_drafts
```

M4-D 新增：

- `event_cards`
- `editorial_packs`
- `draft_generation_runs`
- `editorial_drafts`
- `draft_claim_references`

0013 down revision 为 `20260809_0012`，未修改 0001～0012。

## Admin API

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

所有写操作要求 Admin Token + `X-Actor-ID`。

## 完整验收命令

```bash
ruff check .
mypy apps packages
pytest

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

Definition 第二次同步必须 `created=0 / updated=0 / failed=0`。

## 下一阶段

下一阶段为 **M5-A**，当前仍为 `NOT STARTED`。

开始 M5-A 时必须：

1. 先确认 M4 文档收口 PR 已人工合并；
2. 拉取当时最新 `main`；
3. 从最新 `main` 新建独立 M5-A 分支；
4. 不得从 `feature/m4d-editorial-pack`、`feature/m4c-trend-editorial-scoring` 或本次文档分支继续派生；
5. M5-A 的范围与 Gate 需单独确认，不能把 M4-D 收口当作 M5 功能开工。