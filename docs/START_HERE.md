# AI 编辑部项目开发入口

## 当前阶段

```text
M1 Engineering COMPLETE / 已合并
M2 Engineering COMPLETE / 已合并
M2 deferred real-smoke Gate for MVP/M5 closeout = SATISFIED / CLOSED
M2 broader real-world platform coverage = PARTIAL（当前明确证明 Bilibili low-volume）
M3 Overall Engineering COMPLETE / 已合并
M4-A AI Gateway COMPLETE / 已合并
M4-B Evidence / Claim COMPLETE / 已合并
M4-C Trend / Editorial Score COMPLETE / 已合并
M4-D Event Card / Draft COMPLETE / 已合并
M4 Overall Engineering COMPLETE
M5-A Editorial Workbench COMPLETE / MERGED
M5-B Daily Candidates / Editorial Workflow COMPLETE / MERGED
M5-C Publication / Performance Feedback COMPLETE / MERGED
M5-D A Engineering Hardening PASS
M5-D B Real Platform Smoke PASS（Bilibili low-volume only）
M5-D C Production AI Provider PASS
M5-D D Full Human-in-loop E2E PASS
M5 Overall COMPLETE
```

PR #23 `feat: 完成 M5-D Hardening与MVP收口` 已于 2026-08-13 人工合并到 `main`。M5-D 最终真实验证报告为 PASS，正式 `verify_m5d_e2e = PASS`。

当前正式路线不是 M6，而是进入 Post-MVP / V1 readiness，然后按规划推进：

```text
M5
→ V1-A / V1-B / V1-C / V1-D
→ V1.5
→ V2
→ P1
→ P2
```

当前优先入口文档：

- `docs/POST_MVP_V1_READINESS_CHECKLIST.md`
- `docs/M5_ACCEPTANCE_REPORT.md`
- `docs/M5D_REAL_VALIDATION_REPORT.md`
- `docs/MVP_RUNBOOK.md`
- `docs/AI编辑部_综合开发实施规划_V1.2.md`
- `docs/DECISIONS.md`
- `docs/CHANGELOG.md`

## 开发前必读

1. `docs/POST_MVP_V1_READINESS_CHECKLIST.md`
2. `docs/AI编辑部_综合开发实施规划_V1.2.md`
3. `docs/AI编辑部_技术开发文档_V1.2.md`
4. `docs/AI编辑部_PRD_V1.2.md`
5. `docs/DECISIONS.md`
6. `docs/M5_ACCEPTANCE_REPORT.md`
7. `docs/M5D_REAL_VALIDATION_REPORT.md`
8. `docs/MVP_RUNBOOK.md`
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

## M5-D 最终真实验证

真实链路已经验证：

```text
Real Collection
→ RawSignal
→ Event
→ Evidence Extraction
→ Human Claim Verification
→ Trend
→ Production Editorial Scoring
→ Candidate
→ Human Adopt
→ Card / Pack
→ Production AI Draft
```

真实平台范围：

```text
Bilibili low-volume smoke only
CollectionRun = 19bed81a-ac50-4251-ab57-7eb841a91bfb
RawSignal = f2e03174-3023-4e64-8389-2a8724fabb82
collected / inserted / failed = 1 / 1 / 0
platform risk = none observed
```

Production Provider：

```text
provider = deepseek-production
model = deepseek-v4-flash
```

Evidence Extraction、Editorial Scoring、Draft Generation 均已存在真实正式业务 Invocation，并通过正式 provenance verifier。

该结论只证明 MVP Closeout 所需的一平台真实 E2E，不代表七个 MediaCrawler 平台全部 production validated，也不代表大规模长期运行稳定性已经验证。

## M2 Real Smoke 后续语义

`docs/M2_ACCEPTANCE_REPORT.md` 中的：

```text
M2 Real Smoke Validation = DEFERRED / NOT_TESTED
```

是 M2 当时的历史验收状态，不重写历史。

根据后续 D-030 与 M5-D Bilibili real smoke：

```text
M2 deferred real-smoke Gate for MVP/M5 closeout = SATISFIED / CLOSED
```

但当前逐平台真实覆盖仍必须保守记录：

- Bilibili：已明确真实 smoke；
- Zhihu：Engineering READY，但尚无单独 real smoke evidence；
- Weibo：仍有 low-volume search known limitation，不能猜 API 参数或扩大请求量；
- Douyin / Xiaohongshu / Kuaishou / Baidu Tieba：属于 V1-A 逐平台灰度，不应自动视为已验证。

## M5-A Workbench 能力

Web 继续沿用现有 PageKey 架构，不引入 React Router 或大型 UI Framework。导航按 Editorial / Collection / Configuration / AI 分组。

M5-A 只读查询：

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

## M5-B Daily Candidates / Editorial Workflow

M5-B 使用确定性 Daily Candidate snapshot、候选池读模型和 append-only Human Editorial Decision history。候选排名与人工决定分离；Apply 保持 input idempotency / PostgreSQL concurrency safety，不自动调用 AI、自动发布或改写既有 Event、Evidence、Trend、Score、Card、Pack、Draft 语义。

## M5-C Publication / Performance Feedback

M5-C 记录 Publication 与 Performance Feedback：Workflow Publication 冻结 exact Draft、当前 `adopt` Decision 与候选/评分 provenance；manual backfill 显式保留原因。Performance snapshot 与 CSV import 均 append-only/idempotent，不回写 Candidate Rank、Event lifecycle、Trend、Score、Decision 或 Evidence。

M5-C 已建立 V1-D 所需的数据基础；V1-D 后续重点是接入真实运营数据、来源命中率、采用率与评分校准分析，不重新建立 Publication/Performance 第二套模型。

## AI Generation Policy 技术债

M5-D 暴露并确认以下 Post-MVP 技术债：

```text
evidence_extraction max_output_tokens = 4096
editorial_scoring max_output_tokens = 4096
draft_generation max_output_tokens = 6000
```

当前主要仍由 task 业务代码常量/参数承担。Post-MVP 第一项真正功能开发计划为 task-level AI Generation Policy 配置化：DB/Admin UI 优先，代码 fallback，保留 version/audit，且不得绕过现有 AI Budget。

冻结要求：

- 不创建粗暴全局 `AI_MAX_TOKENS`；
- Editorial Scoring 继续共享 `allowed_risk_levels` 语义；
- `draft-generation-v2` 继续要求 exactly one JSON object；
- 通用 parser 继续严格 `json.loads`，不增加 malformed JSON repair。

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

## 真实平台风险边界

真实平台验证继续使用：

- 独立低价值测试账号；
- visible Chrome/CDP；
- stable controlled browser profile；
- concurrency=1；
- low-volume；
- 不做 CAPTCHA 破解；
- 不做 fingerprint spoofing；
- 不在 restriction 后自动换号；
- 不做 proxy rotation 绕过；
- 403/406/429、CAPTCHA、automation detection、账号异常、login invalidation、`REVIEW_REQUIRED`、`RESTRICTED` 等立即停止转人工。

Bilibili 已完成真实 smoke，不为追求“全平台 PASS”重复增加风险。Weibo 当前 known limitation 不通过猜测未证实参数解决。

## 当前下一步

当前不是 M6，也不再进行 M5-D。

执行顺序以 `docs/POST_MVP_V1_READINESS_CHECKLIST.md` 为准：

```text
1. Post-MVP readiness / 文档 / baseline 收口
2. 建立 MVP Git tag / GitHub Release
3. AI Generation Policy v1
4. P1-lite 最低 operability
5. V1-A 单平台灰度
6. V1-B Lifecycle / Trend
7. V1-C Multimedia
8. V1-D Feedback / Calibration
```

Zhihu / Weibo 的 M2 coverage follow-up 是非阻塞旁路线，不重新打开 M2 Gate。
