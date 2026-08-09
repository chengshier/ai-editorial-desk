# Changelog

## 2026-08-09 - M4-D Event Card / Draft Engineering Closure

### Added

- 新增 migration `20260809_0013_m4d_editorial_pack_drafts`；
- 新增 versioned / append-only `event_cards`，以 `event-card-v1` 固化 Event + Evidence + Trend + Effective Editorial Assessment provenance；
- 新增 versioned / append-only `editorial_packs`，以 `editorial-pack-v1` 整理 source / timeline / material metadata / warning / suggested angles；
- 新增 `draft_generation_runs`、`editorial_drafts`、`draft_claim_references`；
- 新增 `draft-service-v1 / draft-generation-v1 / draft-schema-v1`；
- 新增 `short_30s / standard_90s / deep_180s` Evidence-aware Draft / Script generation；
- 新增 Claim citation chain、unsupported / cross-event Claim 与 Unknown 拒绝、false / disputed / single_source / investigating 安全语义；
- 新增 Risk-aware Draft path、stale editorial context protection 与 merged Event protection；
- 新增 Human Draft / Human Revision append-only version chain，AI 原始稿不被覆盖；
- 新增 deterministic Markdown Export，不再次调用 AI；
- 新增 M4-D Admin API 与 PostgreSQL constraint / concurrency / migration / API / export 回归测试。

### Validation

- PR #18 `feat: 完成 M4-D Event Card、Draft与阶段收口` 已人工 Squash merge；
- PR #18 final exact-head `9ae6033b57111a800c24c3eb69aa6ef694e53235` 的 GitHub Actions run `31312854489` / #383 为 `completed / success`；
- Python / Web Gate 均 success；full pytest `489 passed, 1 warning`；
- Alembic five-step round trip 与 Connector Definition sync ×2 success；
- `M4-D Event Card / Draft = COMPLETE`；
- `M4 Overall Engineering = COMPLETE`；
- `Production AI Provider Validation = NOT_TESTED`；
- `M2 Real Smoke Validation = DEFERRED / NOT_TESTED`；
- `M2 Real-world Validation = NOT COMPLETE`；
- `M5 = NOT STARTED`。

## 2026-08-09 - M4-C Trend / Editorial Score Engineering

### Added

- 新增 `event_trend_snapshots`：版本化、append-only、输入幂等的 Event Trend 派生 artifact；
- 新增 `editorial_scoring_runs`：业务评分执行与 AI Invocation 的关联记录；
- 新增 `editorial_scores`：七维 0..100 Editorial Score、Service 重算 `traffic_total`、R0-R4 risk candidate 与有限 recommended format；
- 新增 `editorial_score_overrides`：Actor + reason 的 append-only Human override；
- 新增 migration `20260809_0012_m4c_trend_editorial_scoring`；
- 新增 `packages/editorial/`：Trend calculation、Evidence-aware scoring input、AIGateway scoring、Risk guard、Human manual score、Effective view；
- 新增 M4-C Admin API；
- 新增 fixed-UTC Trend、AI scoring、Risk、Human、PostgreSQL constraint/concurrency、migration 与 Admin API 测试。

### Decisions

- Trend 与 Editorial Score 分层；
- Trend version：`trend-calculation-v1`；
- `signal_velocity` 使用 `new_signal_count / window_hours`；
- `interaction_velocity` 因缺少跨平台统一互动语义保持 NULL / `INTERACTION_NORMALIZATION_UNAVAILABLE`；
- `cn_gap` 因缺少 Source geography 保持 NULL / `GEOGRAPHY_CLASSIFICATION_UNAVAILABLE`；
- `semantic_novelty` 因当前无 Event centroid/稳定 Event-history proxy 保持 NULL / `EVENT_SEMANTIC_NOVELTY_UNAVAILABLE`；
- Score template：`general / score-template-general-v1`，七维权重 `20/15/15/15/15/10/10`；
- scoring/prompt/schema：`editorial-score-service-v1 / editorial-scoring-v1 / editorial-score-schema-v1`；
- `traffic_total` 只由 Service 重算；
- AI 不修改 Evidence/Event membership/Event.status；
- Human manual score 不伪造 AI Invocation；Human override 优先且历史不覆盖；
- AI 只经 `AIGateway.generate_structured(task_key="editorial_scoring")`；
- M4-C 不进入 Event Card、Candidate Pack、标题、Hook、Script、Draft、DailyCandidate 或 Publication Feedback。

### Validation

- M4-C 全部 AI 测试使用 Mock/Fake/MockTransport；
- `Production AI Provider Validation = NOT_TESTED`；
- `M2 Real Smoke Validation = DEFERRED / NOT_TESTED`；
- `M2 Real-world Validation = NOT COMPLETE`；
- `M3 Overall Engineering = COMPLETE`；
- M4-D 在当时尚未开始；其完成记录见本文件上方 M4-D Engineering Closure。

## 2026-08-09 - M4-B Evidence / Claim Engineering

- M4-B 建立 `evidence_extraction_runs / evidence_claims / evidence_claim_sources / event_unknowns`；
- Evidence 必须追溯到目标 Event 内真实 RawSignal；
- AI 只能产生 candidate，不可自动 confirmed/false；
- Human terminal verification 要求 Actor + reason + Evidence 条件；
- Prompt/Schema/Extraction version 显式；
- AIGateway 调用在数据库长事务之外；
- Preview/Apply、PARTIAL、merged Event、Human priority 与 PostgreSQL provenance/并发均完成工程验证；
- `Production AI Provider Validation = NOT_TESTED`。

## 2026-08-09 - M4-A AI Gateway Engineering

- 建立 Provider / Model / Task Route / Invocation / Attempt / Budget 基础；
- structured output schema validation、bounded retry/fallback、usage/cost audit；
- 建立 `evidence_extraction` 与 `editorial_scoring` route seed，默认禁用；
- M3 Signal Embedding 可通过 Gateway bridge 复用 M4-A；
- Production Provider Validation 独立，Mock/Fake 不等于真实验证。

## 2026-08-08 - M3 Overall Engineering

- 完成 Event / EventSignal；
- 完成 versioned Signal Embedding；
- 完成 deterministic matching / clustering；
- 完成 merge/split/human boundary/reprocess；
- 完成 offline evaluation、convergence、PostgreSQL concurrency 与 performance baseline；
- `M3 Overall Engineering = COMPLETE`。

## 2026-08-07 - M2 Engineering

- 完成 MediaCrawler 主系统集成层；
- 完成七平台 Mapper / Schema / capability；
- 完成 checkpoint / incremental / account profile / signature / risk 工程增强；
- 完成安全低量 smoke gate 与 preflight 工程；
- `M2 Engineering = COMPLETE`；
- `M2 Real Smoke Validation = DEFERRED / NOT_TESTED`；
- `M2 Real-world Validation = NOT COMPLETE`。

## 2026-08-06 - M1 Engineering

- 完成 Connector Definition / Instance / Account / Source / RawSignal / Budget / Runtime / Scheduler / Validation 基础；
- 完成 PostgreSQL schema、Admin API、Web 基础与工程回归；
- `M1 Engineering = COMPLETE`。
