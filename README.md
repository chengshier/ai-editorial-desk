# AI Editorial Desk

AI 编辑部系统：面向短视频创作者的多来源信息发现、资料整理、编辑判断与内容生产辅助系统。

**当前工程状态：M1 Engineering COMPLETE；M2 Engineering COMPLETE；M2 Real Smoke Validation = DEFERRED / NOT_TESTED；M2 Real-world Validation = NOT COMPLETE；M3 Overall Engineering COMPLETE；M4-A AI Gateway COMPLETE；M4-B Evidence / Claim COMPLETE；M4-C Trend / Editorial Score COMPLETE；M4-D NOT STARTED；M4 Overall NOT COMPLETE。**

> Production AI Provider Validation 继续 `NOT_TESTED`。CI Fake/Mock/MockTransport 只验证工程契约，不能替代真实生产 Provider Validation；M2 真实平台验证状态也不会因为 M3/M4 工程完成而自动升级。

开发入口见 [`docs/START_HERE.md`](docs/START_HERE.md)，M4 工程验收见 [`docs/M4_ACCEPTANCE_REPORT.md`](docs/M4_ACCEPTANCE_REPORT.md)，架构决定见 [`docs/DECISIONS.md`](docs/DECISIONS.md)。

## 当前处理链

```text
Connector / CollectorRuntime
→ RawSignal / RawSignalComment
→ Event / EventSignal
→ Signal Embedding / Matching / Clustering
→ EvidenceClaim / EvidenceClaimSource / EventUnknown
→ Deterministic Trend Snapshot
→ AIGateway Editorial Scoring
→ Editorial Score + Risk Candidate
→ Human Manual Score / Override
→ Effective Editorial Assessment
```

M4-C 中 Trend 回答“事件是否正在发酵”，Editorial Score 回答“这件事对账号是否值得讲”。两者保持分层，不合并为不可解释的黑箱分数；本阶段不建立 DailyCandidate/TOP Pool，也不生成标题、Hook、Event Card、Script 或 Draft。

## M4-C Trend

版本：`trend-calculation-v1`。

`event_trend_snapshots` 是不可变、版本化的派生 artifact；同一 Event / window / calculation version / input hash 重复计算幂等。

当前确定性能力：

- `signal_count` / `new_signal_count`
- `source_count` / `platform_count`
- `signal_velocity = new_signal_count / window_hours`
- `cross_source` / `cross_platform`
- `update_value` 与原始 component metrics

当前明确不可用：

- `interaction_velocity = NULL`：RawSignal.metrics 没有可靠跨平台 interaction normalization；
- `cn_gap = NULL`：Source 没有可靠 country/region/market classification；
- `semantic_novelty = NULL`：当前没有版本化 Event centroid，也没有已验证且足够简单的 Event-history novelty proxy；
- media availability：当前没有统一可靠的媒体分类字段。

`feature_availability` 与 `component_metrics.unavailable_reasons` 明确区分 unavailable 与数值 `0`。

## M4-C Editorial Score

版本：

- template key：`general`
- template version：`score-template-general-v1`
- scoring version：`editorial-score-service-v1`
- prompt version：`editorial-scoring-v1`
- schema version：`editorial-score-schema-v1`

七个维度统一为 `0..100 integer`：

| Dimension | Weight |
|---|---:|
| emotion | 20 |
| information_gap | 15 |
| visual_value | 15 |
| user_relevance | 15 |
| discussion | 15 |
| novelty | 10 |
| extendability | 10 |

`traffic_total` 不信任模型输出，由 Service 确定性重算：

```text
sum(dimension_score * weight) / 100
```

历史 Score append-only；rerun、新模型或未来新模板不能 silent overwrite 旧记录。

## Risk / Recommended Format / Human Priority

AI 只提出 `R0..R4` risk candidate 与有限 format 候选：

- `daily_compilation`
- `quick_explainer`
- `fact_check`
- `deep_dive`
- `entertainment`
- `consumer_safety`

Risk consistency guard 至少保证：无 Evidence、无 confirmed Claim、全部 single_source/disputed、或仍有 open Unknown 时，AI 不能给出 R0。R4 表达当前表达路径存在高风险，不删除 Event；被证伪 Claim 仍可成为 `fact_check` 主题。

人工可创建完整 Human Score，无需伪造 AI Invocation；也可对七维、risk、recommended format 创建 append-only override。人工写入要求 Actor + reason + AuditLog。Effective view 同时保留原始 Score 与人工决定，后续 AI rerun 不会静默抹掉 Human override。

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

所有写操作继续要求 Admin Token + `X-Actor-ID`。API 不返回 RawSignal `raw_payload`、credential、Authorization、完整 Prompt 或 embedding vector。

## AIGateway 边界

M4-C AI Scoring 只允许：

```text
EditorialScoringInputBuilder
→ AIGateway.generate_structured(task_key="editorial_scoring")
→ Route
→ Budget
→ Retry / Fallback
→ Provider adapter
→ Structured Schema Validation
→ Invocation / Attempt / Usage / Cost
→ M4-C Risk Guard
→ EditorialScore
```

Provider 调用位于数据库长事务之外。Preview 仍可能产生 Invocation/token/cost，但不写正式 EditorialScore。

## 数据库迁移

当前 migration head：`20260809_0012_m4c_trend_editorial_scoring`。

新增：

- `event_trend_snapshots`
- `editorial_scoring_runs`
- `editorial_scores`
- `editorial_score_overrides`

0012 基于 0011，未修改 0001～0011。

## 基础验收

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

所有 CI AI 测试保持离线。

## 下一阶段边界

PR #17 保持 Open，不自行合并。只有 PR #17 人工合并后，才能从最新 `main` 独立进入 M4-D；M4-D 才处理 Event Card / Candidate Pack / Script / Draft。