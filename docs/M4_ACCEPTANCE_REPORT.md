# M4 Acceptance Report

## 1. 阶段状态

```text
M4-A AI Gateway：COMPLETE
M4-B Evidence / Claim：COMPLETE
M4-C Trend / Editorial Score：COMPLETE
M4-D Event Card / Script：NOT STARTED
M4 Overall：NOT COMPLETE
Production AI Provider Validation：NOT_TESTED
```

M4-A / M4-B / M4-C 的 COMPLETE 均为工程完成口径，不代表生产 Provider 已真实联网验证，也不代表 M4 Overall 完成。

M1-M3 状态继续保持：

```text
M1 Engineering COMPLETE
M2 Engineering COMPLETE
M2 Real Smoke Validation DEFERRED / NOT_TESTED
M2 Real-world Validation NOT COMPLETE
M3 Overall Engineering COMPLETE
```

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

M4-C 不直接调用 Provider URL，Editorial Scoring 必须通过 `AIGateway.generate_structured(task_key="editorial_scoring")`。

## 3. M4-B：Evidence / Claim

状态：`COMPLETE`。

M4-C 只读取以下 M4-B artifact：

- `EvidenceClaim`；
- `EvidenceClaimSource`；
- `EventUnknown`；
- Claim verification state；
- Claim source count。

Editorial Scoring 不得修改 Claim verification，不创建/确认 Claim，不删除 Unknown，也不修改 RawSignal。

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

核心字段：

- `event_id`
- `calculation_version`
- `window_start_at`
- `window_end_at`
- `signal_count`
- `new_signal_count`
- `source_count`
- `platform_count`
- `signal_velocity`
- `interaction_velocity`
- `cross_source`
- `cross_platform`
- `semantic_novelty`
- `cn_gap`
- `update_value`
- `feature_availability`
- `component_metrics`
- `input_hash`
- `created_at`

版本：`trend-calculation-v1`。

同一 Event / version / window / input hash 使用 PostgreSQL 唯一约束与 insert-on-conflict 实现幂等。

### 4.3 Trend v1 可用性

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

原因：当前 RawSignal.metrics 不具备跨平台统一互动语义；Source 不具备可靠 geography；M3 没有 Event centroid，也没有必要在 M4-C 为单一字段破坏版本化原则。

NULL/unavailable 不等于 0。

### 4.4 Update Value

第一版只使用可观察数据：

```text
min(new_signal_count, 5) * 6
+ min(new_claim_count, 2) * 10
+ min(new_confirmed_or_investigating_claim_count, 2) * 15
+ min(new_official_response_signal_count, 1) * 10
+ min(correction_count, 1) * 10
```

结果范围 0..100，且 `component_metrics` 保存原始组件与公式，不把“新增画面”等当前不可验证数据拍脑袋计分。

### 4.5 Editorial Score

Score 是版本化分析 artifact，不 update 覆盖旧结果。

七维：

- `emotion`
- `information_gap`
- `visual_value`
- `user_relevance`
- `discussion`
- `novelty`
- `extendability`

统一 scale：`0..100 integer`。

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

### 4.6 Scoring Run / Prompt / Schema

`editorial_scoring_runs` 保存业务执行和 AI Invocation 的关系，不重复保存 Provider token/cost。

版本：

```text
prompt_version = editorial-scoring-v1
schema_version = editorial-score-schema-v1
scoring_version = editorial-score-service-v1
```

Scoring input 优先使用 Event + Trend Snapshot + Evidence/Unknown 摘要；不重新发送所有 RawSignal 正文，不发送 raw_payload、credential、Authorization、完整 comment dump 或 embedding vector。

Source-derived 内容被明确标记为 untrusted data，不能成为 Prompt 指令。

### 4.7 Risk

Risk level：`R0 / R1 / R2 / R3 / R4`。

AI 只产生 risk candidate。M4-C consistency guard 至少执行：

- 无 Evidence → AI 不得 R0；
- 无 confirmed Claim → AI 不得 R0；
- 全部 Claim 为 single_source/disputed → AI 不得 R0；
- 仍有 open Unknown → AI 不得 R0。

没有建立“微博=R3 / 某平台=R0”式平台可信度硬编码。

R4 表示当前推荐表达路径存在高风险，不删除 Event；已证伪内容可作为 `fact_check` 主题。

### 4.8 Recommended Format

有限 key：

- `daily_compilation`
- `quick_explainer`
- `fact_check`
- `deep_dive`
- `entertainment`
- `consumer_safety`

只表示候选形式，不生成标题、封面文案、Hook、Event Card narrative、Script 或 Draft。

### 4.9 Human Manual Score / Override

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

### 4.10 Preview / Apply / Provider Failure

Preview：

- 可产生真实 Invocation / token / cost / budget usage；
- 不写正式 EditorialScore。

Apply：

1. 短事务读取安全 snapshot；
2. 结束事务；
3. AIGateway structured call；
4. Service/risk 校验；
5. 新短事务重新确认 Event active；
6. 保存 Run/Score。

Provider/route/budget/schema 失败必须显式失败；不得 fallback 到 test Fake 后伪造生产 AI Score。Human manual score 不依赖 Provider。

### 4.11 Merged Event

当 `merged_into_event_id != NULL`：

- 禁止 source Event 新建 Trend；
- 禁止新建 Score；
- 禁止新建 Override；
- 返回 `EVENT_MERGED + target_event_id`；
- 历史 Trend / Score 仍可读取。

M4-C 不自动修改 Event.status，也不修改 M3 membership/cluster。

## 5. Admin API

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

所有写操作要求 Admin Token + `X-Actor-ID`。API 不返回 raw_payload、credential、Authorization、完整 Prompt 或 vector。

## 6. 测试与回归

M4-C 新增覆盖：

- fixed UTC Trend；
- signal velocity；
- single/multi source；
- single/multi platform；
- interactions unavailable；
- geography unavailable；
- semantic novelty unavailable；
- official response / correction update components；
- resolved / merged Event；
- AI score七维 / total重算；
- invalid score / risk / format；
- route disabled / budget exceeded / provider unavailable；
- Evidence-aware R0 guard；
- R4 fact-check；
- manual score / override / Audit；
- AI rerun不覆盖 Human；
- PostgreSQL CHECK / FK / RESTRICT；
- Trend与AI Score并发幂等；
- migration downgrade；
- Admin API安全输出。

完整 CI 继续运行：

- Ruff；
- mypy；
- full pytest；
- M3 concurrent regression；
- M3 offline engineering evaluation；
- M3 performance baseline；
- Alembic five-step round trip；
- connector definition sync ×2；
- Web lint/typecheck/test/build。

所有 AI 测试离线，未调用真实付费 Provider。

## 7. Production Provider Validation

```text
Production AI Provider Validation = NOT_TESTED
```

M4-C Engineering COMPLETE 不要求真实付费 Provider 验证。只有后续人工提供生产 credential 并完成真实网络调用，才能单独更新该状态。

## 8. M4-D 准入

M4-D 当前：`NOT STARTED`。

PR #17 保持 Open，不自行合并。只有 M4-C PR 人工合并后，才允许从最新 `main` 创建独立 M4-D 分支；不得从本 feature 分支继续派生。