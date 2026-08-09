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
M4-C Trend / Editorial Score COMPLETE / PR #17 Open
M4-D Event Card / Script NOT STARTED
M4 Overall NOT COMPLETE
Production AI Provider Validation NOT_TESTED
M5 NOT STARTED
```

当前分支：

```text
feature/m4c-trend-editorial-scoring
```

当前 PR：

```text
#17 feat: 完成 M4-C Trend与Editorial Score基础
```

PR 保持 Open，不自行合并。

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
```

## M4-C 冻结语义

### Trend != Editorial Score

Trend 回答：事件是否正在发酵。

Editorial Score 回答：事件对账号是否值得讲。

M4-C 不把规则/趋势特征和 AI 语义评分混成一个最终黑箱，也不建立 DailyCandidate/TOP5/TOP10/TOP20。

### Trend Snapshot

版本：`trend-calculation-v1`。

`event_trend_snapshots` 是 append-only、版本化、可幂等重算的派生 artifact。计算必须使用显式 UTC window，并且 window 有上限，不依赖 `datetime.now()` 作为测试语义。

当前可用：

- signal velocity；
- source/platform spread；
- cross_source/cross_platform；
- 基于真实 Signal/Claim/official_response/correction 的 update_value component。

当前不可用：

- interaction velocity：`INTERACTION_NORMALIZATION_UNAVAILABLE`；
- cn_gap：`GEOGRAPHY_CLASSIFICATION_UNAVAILABLE`；
- semantic novelty：`EVENT_SEMANTIC_NOVELTY_UNAVAILABLE`；
- media availability：`MEDIA_CLASSIFICATION_UNAVAILABLE`。

禁止用平台名推断国内/海外，禁止把不同平台互动数直接相加，禁止为了 novelty 临时向 Event 写 centroid。

### Editorial Score

版本：

```text
score template: general
score template version: score-template-general-v1
scoring version: editorial-score-service-v1
prompt version: editorial-scoring-v1
schema version: editorial-score-schema-v1
```

七维统一 `0..100 integer`：

```text
emotion             20
information_gap     15
visual_value        15
user_relevance      15
discussion          15
novelty             10
extendability       10
```

`traffic_total = sum(dimension * weight) / 100`，由 Service 重算。模型返回的 total 不作为业务真相。

### Evidence / Risk 边界

Scoring 只能读取 Claim verification / source count / Unknown 状态，不能创建、确认、删除或改写 Evidence。

AI 可建议 R0-R4，但至少：

- 无 Evidence 不得 R0；
- 无 confirmed Claim 不得 R0；
- 全部 single_source/disputed 不得 R0；
- 存在 open Unknown 不得 R0。

R4 不删除 Event；被证伪内容仍可作为 `fact_check` 候选。

### Human Priority

Human manual score：

- 完整七维；
- Actor + reason；
- `source_type=human`；
- 不创建 Fake AI Invocation；
- 写 AuditLog。

Human override：

- append-only；
- 可覆盖七维、risk、recommended format；
- Actor + reason；
- 原始 Score 保留；
- effective view 应用人工决定；
- 后续 AI rerun 可以新建 Score，但不能 silent overwrite Human 决定。

## AIGateway 唯一路径

Editorial Scoring 必须使用：

```text
AIGateway.generate_structured(task_key="editorial_scoring")
```

完整经过 Route / Budget / Retry / Fallback / Schema / Invocation / Attempt / Usage / Cost。Provider 网络调用放在数据库长事务之外。Preview 不是 free，但不能写正式 EditorialScore。

Production AI Provider Validation 仍为 `NOT_TESTED`，CI Mock/Fake 成功不能改写该状态。

## Migration

当前 head：

```text
20260809_0012_m4c_trend_editorial_scoring
```

M4-C 新增：

- `event_trend_snapshots`
- `editorial_scoring_runs`
- `editorial_scores`
- `editorial_score_overrides`

没有修改 0001～0011。

## Admin API

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

M4-D 仍为 `NOT STARTED`。只有 PR #17 人工合并后，才能基于最新 `main` 新建独立 M4-D 分支；不得从 `feature/m4c-trend-editorial-scoring` 继续派生。M4-D 才允许进入 Event Card / Candidate Pack / Script / Draft。