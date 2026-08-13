# Changelog

## 2026-08-13 - M5-D Real Validation / MVP Closeout / Post-MVP Readiness

### Final Validation / Merge

- M5-D A Engineering Hardening = PASS；
- M5-D B Real Platform Smoke = PASS，当前真实范围仅为 Bilibili low-volume smoke；
- M5-D C Production AI Provider Validation = PASS，Provider=`deepseek-production`，model=`deepseek-v4-flash`；
- M5-D D Full Human-in-loop MVP E2E = PASS；
- formal `verify_m5d_e2e = PASS`；
- `docs/M5D_REAL_VALIDATION_REPORT.md` 已形成最终 PASS 证据；
- PR #23 `feat: 完成 M5-D Hardening与MVP收口` 已人工合并；
- merge commit `8ab9200172786705f9e73093646e3d3d3507ee2f` 的 GitHub Actions `python` / `web` 均 success；
- `M5 Overall = COMPLETE`。

### Real Platform / M2 Boundary

- Bilibili real smoke：CollectionRun `19bed81a-ac50-4251-ab57-7eb841a91bfb`；RawSignal `f2e03174-3023-4e64-8389-2a8724fabb82`；collected=1、inserted=1、failed=0、risk=none observed；
- 该 Bilibili 证据满足 D-030 的 MVP real-platform Gate，因此 `M2 deferred real-smoke Gate for MVP/M5 closeout = SATISFIED / CLOSED`；
- 不回写 M2 当时 Acceptance 的历史 `DEFERRED / NOT_TESTED` 事实；
- 当前不宣称 Zhihu、Weibo、Douyin、Xiaohongshu、Kuaishou、Baidu Tieba 已有单独 real smoke；
- 不宣称 `All MediaCrawler platforms have been production validated`；
- Weibo low-volume search known limitation 继续保留，不通过猜 API 参数、扩大请求量、换号或代理轮换追求 PASS。

### Post-MVP / V1 Readiness

- 新增 `docs/POST_MVP_V1_READINESS_CHECKLIST.md`，明确正式路线不存在 M6；
- 正式后续路线继续为 `M5 → V1-A/V1-B/V1-C/V1-D → V1.5 → V2 → P1 → P2`；
- Post-MVP 第一项真正功能开发确定为 AI Generation Policy v1；
- AI Generation Policy 第一版优先解决 `evidence_extraction / editorial_scoring / draft_generation` 的 task-level `max_output_tokens` 配置化；
- 优先复用现有 versioned `AITaskRouteRecord` / route config，DB/Admin UI 优先、代码常量 fallback、保留 audit/versioning，且不绕过 AI Budget；
- Editorial Scoring 继续共享 `allowed_risk_levels` / R0 eligibility semantics；
- `draft-generation-v2` 继续 exactly-one-JSON + strict schema + strict `json.loads`，不增加 malformed JSON repair；
- P1-lite 只做 7-day/30-day soak、backup/restore、disk/backlog/provider failure/risk/checkpoint/budget 等最低 operability，不提前演变为完整 Redis/Worker P1 重构；
- V1-A 按单平台灰度推进，不一次打开抖音/小红书/快手/贴吧全部平台。

---

## 2026-08-10 - M5-D Engineering Hardening / MVP Real Validation Harness

### Added / Hardened

- 新增只读 `packages/validation/`：M5-D Preflight、MVP Doctor、Production business Invocation verifier 与 Full E2E provenance verifier；
- 新增统一 Validation output/report 脱敏，禁止 Cookie、Authorization、API Key、credential、password、完整 Prompt 与 browser profile 路径进入提交报告；
- 新增 `scripts/m5d_preflight.py`、`scripts/mvp_doctor.py`、`scripts/run_m5d_platform_smoke.py`、`scripts/run_m5d_provider_validation.py`、`scripts/verify_m5d_e2e.py`；
- Real Platform wrapper 继续调用既有 M2 MediaCrawler smoke / CollectorRuntime 主链，不建立第二套采集器，并禁止在普通 CI 执行真实平台操作；
- Production Provider validation 要求显式 `--confirm-paid-call`；Connection Test 单独成功仍保持 `PENDING_BUSINESS_INVOCATION`，必须再核验正式 AIGateway 业务 Invocation/Attempt；
- Harden `AIConnectionTester`：只要测试注入 ProviderFactory/MockTransport，就不具备提升真实 Provider `validation_status` 的资格；
- Production business Invocation verifier 额外要求同 `provider_key` 的启用 Provider 已有独立 `validation_status=PASSED`，Fake/Mock identity 或未验证 Provider 均 BLOCK；
- 新增 PostgreSQL Hardening 回归：Account risk block、显式 Collection Budget、migration mismatch、Fake Provider gate、Mock validation-status guard、secret redaction；
- 新增 `docs/MVP_RUNBOOK.md` 与初始 `NOT_RUN` 的 `docs/M5D_REAL_VALIDATION_REPORT.md`；
- 新增 D-030，冻结 Engineering CI、Real Platform、Production Provider、Human E2E 四类独立证据门槛。

### Status / Boundaries

- `M5-A = COMPLETE / MERGED`；`M5-B = COMPLETE / MERGED`；`M5-C = COMPLETE / MERGED`；
- `M5-D Engineering Hardening = IN PROGRESS / PR #23 OPEN`；
- `Real Platform Smoke = PENDING / NOT_RUN`；
- `Production AI Provider Validation = NOT_TESTED`；
- `Full Human-in-loop E2E = PENDING / NOT_RUN`；
- `M5 Overall = NOT COMPLETE`；
- `M2 Real Smoke Validation = DEFERRED / NOT_TESTED`；`M2 Real-world Validation = NOT COMPLETE`；
- GitHub CI、Fake/Mock、synthetic fixture 与 offline E2E 只能证明 Engineering Hardening；真实 Platform/Provider/Human E2E 必须由受控本地环境从绿色 exact-head 执行；
- M5-D 默认 NO NEW MIGRATION，Alembic head 继续 `20260810_0015_m5c_publication_performance`；
- 不自动发布、不接平台发布 API、不自动 Adopt、不绕过 Risk/Budget、不做 CAPTCHA 破解、fingerprint spoofing、账号/代理轮换或风险后持续重试。

## 2026-08-10 - M5-C Publication / Performance Feedback Engineering Closure

### Added

- 新增 `20260810_0015_m5c_publication_performance`：Publication、Performance Import Run 与 append-only Performance Snapshot；
- Workflow Publication 冻结 exact Draft、current adopt Decision、Candidate/Score/Risk provenance；Manual Backfill 显式保留原因；
- 新增手工与 CSV Performance Feedback，覆盖同快照幂等、append-only correction、空值/百分比/时区校验与并发 import；
- Web 接入 Publications、Performance Feedback 与 Candidate Published count；旧 Candidates 页面测试改为注入完整类型安全 `PublicationApi`；
- 修正 M5-C fixture 与 metadata/migration regression，使测试对齐 M5-B 当前持久化契约、迁移边界与全量执行顺序；Windows 使用 junction 验证 profile-root escape safety。

### Validation / Status

- 本地 Python full suite：`511 passed, 1 warning`；M3 concurrent / offline evaluation / performance baseline、ruff、mypy、Alembic 五步、Definition sync ×2 均通过；
- Web `typecheck`、`test -- --run`（20 passed）、`lint`（0 errors，3 个既有 warning）与 `build` 均通过；
- `M5-A = COMPLETE / MERGED`；`M5-B = COMPLETE / MERGED`；`M5-C = COMPLETE / MERGED`；M5-D 状态以后续记录为准；
- `Production AI Provider Validation = NOT_TESTED`；`M2 Real Smoke Validation = DEFERRED / NOT_TESTED`；`M2 Real-world Validation = NOT COMPLETE`。

## 2026-08-10 - M5-B Daily Candidates / Editorial Workflow Engineering Closure

### Added

- 新增确定性 Daily Candidate snapshot、候选池读模型与人工 Editorial Decision history；Candidate Rank 与 Human Decision 明确分离；
- Candidate Apply 覆盖 input idempotency、PostgreSQL concurrency safety、stale protection、risk/archive/restore/drop 与 evidence merge；
- 新增 migration `20260810_0014_m5b_daily_candidates`，并在全新独立 PostgreSQL 测试库完成 Alembic 五步往返验证；
- 修正 M5-B fixture 历史时间与 test cleanup，使候选窗口和并发断言在真实语义下稳定执行；
- 修正 Web 测试中的过期 M5-A 文案断言与 lifecycle/decision 描述断言。

### Status / Boundaries

- `M5-A = COMPLETE / MERGED`；
- `M5-B = COMPLETE / PR #21 OPEN`（历史记录；后续已 merged）；
- 当时 `M5-C = NOT STARTED`，`M5-D = NOT STARTED`，`M5 Overall = NOT COMPLETE`；
- `Production AI Provider Validation = NOT_TESTED`；
- `M2 Real Smoke Validation = DEFERRED / NOT_TESTED`，`M2 Real-world Validation = NOT COMPLETE`；
- Windows `WinError 1314` symlink privilege 仅记录为本地环境限制；不改变 Linux exact-head CI 的测试语义或验收责任。

## 2026-08-09 - M5-A Editorial Workbench Engineering

### Added

- 新增只读 `EditorialWorkbenchQueryService` 与 `/api/v1/admin/workbench/overview`、`/events`、`/events/{event_id}`、`/events/{event_id}/signals`；
- Event Explorer 增加分页、lifecycle/category/merged/risk/evidence/score/draft/time/text 筛选，以及 last updated / first seen / Effective Score 普通排序；
- 新增 Editorial Overview 与 Event Workbench：Overview、Evidence、Sources & Timeline、Trend & Score、Card & Pack、Drafts；
- 接入既有 Merge/Split、Evidence verification/Unknown、Trend calculate、AI/manual Score、Human override、Card/Pack、AI Draft、Human Draft/Revision、Markdown Export；
- 新增 Original AI Score / Effective Score / Human Override 可追溯展示、Risk Gate/stale UX、Unavailable != 0、merged Event 只读保护；
- 新增安全 Source URL helper，仅允许 http/https；
- Web 导航按 Editorial / Collection / Configuration / AI 轻量分组，保留全部 M1～M4 管理页；
- 新增 Workbench PostgreSQL 聚合/N+1/敏感字段测试与 Web Mock API 测试。

### Decisions / Boundaries

- Workbench Query API 只读，不复制业务 Write API，也不调用 AI；
- Event lifecycle 与未来 M5-B Editorial Decision 分离；
- M5-A 不自动调用 AI，不自动创建 Artifact，不自动发布；
- unavailable feature 明确显示 reason，不能伪装为数值 0；
- M5-A 不持久化 DailyCandidate/TOP rank/adopt/watch/drop；
- **NO NEW MIGRATION**，Alembic head 保持 `20260809_0013_m4d_editorial_pack_drafts`；
- Production AI Provider Validation 继续 `NOT_TESTED`；
- M2 Real Smoke Validation 继续 `DEFERRED / NOT_TESTED`，M2 Real-world Validation 继续 `NOT COMPLETE`；
- M5-B / M5-C / M5-D 继续 `NOT STARTED`，M5 Overall `NOT COMPLETE`。

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
- `M5 = NOT STARTED`（该历史状态随后由上方 M5-A 记录推进）。

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
- `M3 Overall Engineering = COMPLETE`。

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
