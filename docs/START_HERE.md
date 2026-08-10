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
M4-D Event Card / Draft COMPLETE / 已合并
M4 Overall Engineering COMPLETE
Production AI Provider Validation NOT_TESTED
M5-A Editorial Workbench Engineering COMPLETE / MERGED
M5-B Daily Candidates / Editorial Workflow COMPLETE / MERGED
M5-C Publication / Performance Feedback COMPLETE / MERGED
M5-D Engineering Hardening COMPLETE / PR #23 OPEN
M5-D Real Platform Smoke PENDING / NOT_RUN
M5-D Production AI Provider Validation PENDING / NOT_TESTED
M5-D Full Human-in-loop E2E PENDING / NOT_RUN
M5 Overall NOT COMPLETE
```

M5-A、M5-B、M5-C 已合并。M5-D Phase 1 Engineering Hardening 已在 `feature/m5d-hardening-mvp-closeout` / PR #23 完成工程收口；Real Platform Smoke、Production AI Provider Validation 与 Full Human-in-loop E2E 仍等待受控本地人工真实验证。GitHub CI、Fake Provider、MockTransport、synthetic platform fixture 与 offline E2E 只能证明 Engineering Hardening，不能提升真实验证状态。

详细阶段验收与运行手册见：

- `docs/M5_ACCEPTANCE_REPORT.md`
- `docs/MVP_RUNBOOK.md`
- `docs/M5D_REAL_VALIDATION_REPORT.md`
- `docs/M4_ACCEPTANCE_REPORT.md`
- `docs/M3_ACCEPTANCE_REPORT.md`

## 开发前必读

1. `docs/AI编辑部_综合开发实施规划_V1.2.md`
2. `docs/AI编辑部_技术开发文档_V1.2.md`
3. `docs/AI编辑部_PRD_V1.2.md`
4. `docs/DECISIONS.md`
5. `docs/M5_ACCEPTANCE_REPORT.md`
6. `docs/MVP_RUNBOOK.md`
7. `docs/M4_ACCEPTANCE_REPORT.md`
8. `docs/M3_ACCEPTANCE_REPORT.md`
9. `docs/CHANGELOG.md`

## 当前完整处理链

```text
Connector Definition / Source / Schedule
→ CollectionTask / CollectorRuntime
→ RawSignal / RawSignalComment
→ Event / EventSignal
→ Signal Embedding / Matching / Clustering
→ EvidenceClaim / EvidenceClaimSource / EventUnknown
→ EventTrendSnapshot
→ Effective Editorial Assessment
→ Event Card
→ Editorial Pack
→ Draft / Revision
→ Markdown Export
→ M5-A Editorial Workbench
→ M5-B Daily Candidates / Editorial Workflow
→ M5-C Publication / Performance Feedback
```

M5-D 不新增业务主链，而是围绕上述既有链建立 Preflight、Doctor、真实验证 Harness、只读 provenance verifier、脱敏 Validation Report 与 Runbook。

## M5-A Workbench 能力

Web 继续沿用现有 PageKey 架构，不引入 React Router 或大型 UI Framework。导航按逻辑整理为 Editorial / Collection / Configuration / AI。

M5-A 新增只读查询：

```text
GET /api/v1/admin/workbench/overview
GET /api/v1/admin/workbench/events
GET /api/v1/admin/workbench/events/{event_id}
GET /api/v1/admin/workbench/events/{event_id}/signals
```

所有 Merge/Split、Evidence verification、Unknown、Trend calculate、Score、Card/Pack、Draft/Revision 等写操作继续调用 M3/M4 既有 Admin API，Workbench 不复制业务 Write API。

关键冻结边界：

- Event lifecycle、Algorithmic Candidate Rank 与 Human Editorial Decision 分离；
- Unknown 不是 Fact，single_source 不是 confirmed；
- unavailable 必须显示 `Unavailable + reason`，不能显示假 0；
- Original AI Score 与 Effective Score 同时可追溯，Human Override 明确标记；
- merged Event 历史 Artifact 可读，但新写操作禁用并显示 target Event；
- Workbench Query Service 只读且绝不调用 AI；
- AI Score / Draft Preview / Apply 必须人工显式触发；
- R3/R4、stale context、citation、verification 最终规则仍由原业务 Service/API 决定；
- 不自动 fallback 到 Fake Provider；
- Admin Token / Actor 继续只保存在 `sessionStorage`；
- 页面/API 不展示 raw_payload、credential、Authorization、API Key、Cookie、完整 Prompt 或 embedding vector。

## Production AI Provider Validation

```text
Production AI Provider Validation = NOT_TESTED
```

Mock/Fake CI 成功不能把该状态改成 PASSED。M5-D 进一步冻结：注入测试 ProviderFactory 的 Connection Test 不具备提升真实 validation status 的资格。Production Provider PASS 必须由受控本地真实 credential + 真实 network + Connection Test + 至少一次正式 AIGateway 业务 Invocation/Attempt 共同证明。

## M5-B Daily Candidates / Editorial Workflow

M5-B 使用确定性 Daily Candidate snapshot、候选池读模型和 append-only Human Editorial Decision history。候选排名与人工决定分离；Apply 保持 input idempotency / PostgreSQL concurrency safety，不自动调用 AI、自动发布或改写既有 Event、Evidence、Trend、Score、Card、Pack、Draft 语义。

## M5-C Publication / Performance Feedback

M5-C 记录真实发布与 Performance Feedback：Workflow Publication 冻结 exact Draft、当前 `adopt` Decision 与候选/评分 provenance；manual backfill 显式保留原因。Performance snapshot 与 CSV import 都是 append-only/idempotent，不回写 Candidate Rank、Event lifecycle、Trend、Score、Decision 或 Evidence。

## M5-D Engineering Hardening

Phase 1 已新增/强化：

- `python -m scripts.mvp_doctor`：read-only PASS/WARN/BLOCK 运行检查；
- `python -m scripts.m5d_preflight ...`：真实 Platform/Provider/E2E 前置条件检查；
- `python -m scripts.run_m5d_platform_smoke ... --confirm-real-network`：薄封装现有 M2 MediaCrawler smoke 主链；
- `python -m scripts.run_m5d_provider_validation ... --confirm-paid-call`：真实 Provider Connection Test + 业务 Invocation 核验入口；
- `python -m scripts.verify_m5d_e2e ...`：只读同链 provenance verifier；
- Validation output/report 统一脱敏；
- Fake/Mock validation-status hard gate；
- E2E verifier Fake Provider 与错误 Human Decision provenance 防伪回归；
- `docs/MVP_RUNBOOK.md` 与 `docs/M5D_REAL_VALIDATION_REPORT.md`。

这些工具不会自动登录、自动采集、自动调用 AI、自动 Adopt、自动补建缺失 Artifact 或自动发布。

## Migration

M5-D 无新 migration。当前 Alembic head 继续：

```text
20260810_0015_m5c_publication_performance
```

0015 仅新增 M5-C Publication / Performance Feedback artifact；M5-D Harness/Doctor/Verifier/Report 不建立新的业务真相表。

## 完整 Engineering Gate

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

Definition 第二次同步必须 `created=0 / updated=0 / failed=0`。M3 concurrent regression、offline engineering evaluation、performance baseline 继续作为全量 CI Gate。

## M5-D 真实验证边界

真实平台与真实 Provider 不在普通 GitHub Actions 中运行。Phase 1 Engineering exact-head CI 绿色后，受控本地从同一绿色 HEAD 按 `docs/MVP_RUNBOOK.md` 执行：

```text
M5-D Preflight
→ Human confirmation
→ Bilibili（首选）或 Zhihu 低量 Real Smoke
→ Provider Connection Test
→ real AIGateway business Invocation
→ real Event / Evidence / Trend / AI Score
→ Candidate Pool
→ Human Workbench review + Adopt
→ Card / Pack
→ real AI Draft
→ read-only E2E verifier
→ sanitized validation report
```

出现 403/406/429、CAPTCHA、automation detection、账号异常、login invalidation、`REVIEW_REQUIRED`、`RESTRICTED` 或现有 Risk Guard stop 条件时必须立即停止，不 retry 到成功、不换号、不换代理、不重开 Profile 绕过。

## 当前下一步

当前状态为 **M5-D Engineering Hardening COMPLETE / AWAITING HUMAN REAL VALIDATION**。Real Platform、Production Provider 与 Full Human-in-loop E2E 尚未真实执行，因此：

```text
M5-D Real Platform Smoke PENDING / NOT_RUN
M5-D Production AI Provider Validation PENDING / NOT_TESTED
M5-D Full Human-in-loop E2E PENDING / NOT_RUN
M5 Overall NOT COMPLETE
M2 Real Smoke Validation DEFERRED / NOT_TESTED
M2 Real-world Validation NOT COMPLETE
Production AI Provider Validation NOT_TESTED
```

M5-D 不开始 M6/V1 下一阶段，不自动发布，也不接平台发布 API。