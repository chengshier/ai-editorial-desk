# M5 Acceptance Report

> 本文分别记录 M5 工程阶段与真实验证状态。Engineering CI、Mock/Fake、synthetic fixture 或 offline E2E 不代表真实平台、Production Provider 或 Human-in-loop E2E 已通过。

## 阶段状态

- **M5-A Editorial Workbench：COMPLETE / MERGED**
- **M5-B Daily Candidates / Editorial Workflow：COMPLETE / MERGED**
- **M5-C Publication / Performance Feedback：COMPLETE / MERGED**
- **M5-D Engineering Hardening：COMPLETE / PR #23 OPEN**
- **M5-D Real Platform Smoke：PENDING / NOT_RUN**
- **M5-D Production AI Provider Validation：PENDING / NOT_TESTED**
- **M5-D Full Human-in-loop E2E：PENDING / NOT_RUN**
- **M5 Overall：NOT COMPLETE**

继续保留：

- **M4 Overall Engineering：COMPLETE**
- **Production AI Provider Validation：NOT_TESTED**
- **M2 Real Smoke Validation：DEFERRED / NOT_TESTED**
- **M2 Real-world Validation：NOT COMPLETE**

## M5-A Editorial Workbench

M5-A 将 M1～M4 已有能力整合为日常编辑工作台，不重新实现 Event、Evidence、Trend、Editorial Score、Event Card、Editorial Pack 或 Draft 业务语义。

核心能力包括：

- 只读 Workbench Overview / Event Explorer / Event Detail / Signal projection；
- Event Workbench：Overview、Evidence、Sources & Timeline、Trend & Score、Card & Pack、Drafts；
- Human Evidence、Unknown、Merge/Split、Trend calculate、Human score/override、Human Draft/Revision 继续复用既有业务 API；
- AI Score / Draft Preview 与 Apply 只在用户显式触发后调用 AIGateway；
- Markdown Export 使用 M4-D deterministic backend exporter；
- Query Service 只读且使用 batch/join projection，避免 Event 列表 N+1；
- API/UI 不返回 raw_payload、credential、Authorization、API Key、Cookie、完整 Prompt 或 embedding vector。

冻结边界：Unknown != Fact、single_source != confirmed、Unavailable != 0、Original/Effective Score 可追溯、merged Event 历史可读但禁止新写、Risk/Stale/Citation 规则继续由原业务 Service 强制执行。

## M5-B Daily Candidates / Editorial Workflow

M5-B 新增确定性 Daily Candidate snapshot、候选池读模型和人工 Editorial Decision history。

- Candidate Rank 是 `candidate-ranking-v1` 的算法结果；
- Human Decision (`adopt/watch/drop/archive/restore`) append-only 独立记录；
- Candidate 与 Human Decision 不改变 Event lifecycle；
- Apply 对同一输入幂等，并使用 PostgreSQL 并发保护；
- Adopt 不自动生成 Card/Pack/Draft；
- M5-B 不自动调用 AI、不自动发布、不修改 M3/M4 frozen semantics。

## M5-C Publication / Performance Feedback

M5-C 已合并，并建立真实发布与 Outcome 数据基础。

### Publication record

- `Publication != Adopt`；
- `Publication != Draft`；
- 一条真实平台帖子对应独立 Publication；
- `platform_key` 使用稳定字符串，不建立 Douyin/Bilibili/Weibo 核心 enum；
- workflow 模式要求 active Event、当前 Decision=`adopt`、exact `draft_id`；
- manual_backfill 允许历史 provenance 不完整，但必须 Actor + reason，不伪造 Candidate/Decision/Draft/AI Invocation；
- workflow Publication 冻结 exact Draft chain/version/source/format/duration；
- 冻结发布当时 Candidate run/id/rank、Human Decision、Effective Traffic、Risk、Recommended Format 等 provenance；
- Draft Revision、新 Candidate Run、新 Decision 不回写旧 Publication；
- public URL 仅保存安全 `http/https`，不自动 fetch URL；
- 不保存发布账号 credential、Cookie、Token 或 browser profile。

### Performance Snapshot

- `publication_performance_snapshots` append-only；
- `published_at`、`observed_at`、`created_at` 语义分离；
- 支持 `h1/h24/d7/custom`；
- views/likes/comments/shares/favorites 非负 nullable；
- completion rate 内部 0..1；
- average watch nullable 非负；
- follower delta 允许负数；
- missing metric = NULL，真实 0 才是 0；
- 修正通过新 Snapshot + supersedes provenance，不 silent overwrite；
- snapshot identity 使用稳定 hash 幂等。

### Manual / CSV

- Manual Performance 支持所有核心 metric；
- canonical CSV 版本为 `performance-csv-v1`；
- `completion_rate_percent` 明确使用 0..100 输入；
- blank → NULL；
- observed_at 必须 timezone-aware ISO 8601；
- Preview side-effect free；
- Apply 需要 Actor + confirmation，第一版 all-or-nothing；
- file hash + mapping version 与 snapshot hash 形成双层幂等；
- ImportRun 保留 CSV provenance。

### Feedback projection

Performance Feedback 只读并排展示 Candidate Rank snapshot、Human Decision snapshot、Score/Risk/Format snapshot、Draft version、Publication 与真实指标。

M5-C **不**：

- 自动发布；
- 接平台发布 API；
- 自动改 Candidate Rank；
- 自动改 Editorial Score；
- 自动改 Human Decision；
- 自动改 Evidence verification；
- 自动调 Prompt/weight/model。

## Migration

M5-C 新增 migration：

`20260810_0015_m5c_publication_performance`

M5-D **NO NEW MIGRATION**，当前 Alembic head 继续为 `20260810_0015`。M5-D 的 Harness/Doctor/Verifier/Report 组合现有 Run/Risk/Checkpoint/Provider/Invocation/Artifact 证据，不新建 Validation 真相表。

## M5-D A. Engineering Hardening

Phase 1 Engineering Hardening 已完成：

- `M5DPreflightService`：read-only 检查 DB、migration、Connector/Source、Account/Profile、Collection Budget、Checkpoint、Risk、Provider credential ref、Provider validation、AI Route、AI Budget；
- `MVPDoctorService`：read-only PASS/WARN/BLOCK 运行诊断；
- `verify_business_invocation`：正式业务 Invocation/Attempt/provider identity 核验；
- `verify_m5d_e2e`：只读 CollectionRun→RawSignal→Event→Evidence→Trend→AI Score→Candidate→Human Adopt→Card/Pack→AI Draft provenance verifier；
- Validation output/report recursive secret redaction；
- MediaCrawler real smoke 薄 wrapper，仍调用现有 M2 smoke/CollectorRuntime 主链；
- Production Provider validation CLI，要求显式 `--confirm-paid-call`，Connection Test 单独成功仍不是 Production Validation PASS；
- AIConnectionTester hardening：注入 ProviderFactory/MockTransport 的 Engineering Test 不具备提升 Provider `validation_status` 的资格；
- E2E verifier 防伪回归：Fake/Mock Provider Invocation 必须 FAIL，Decision 非 `adopt` 的错误 provenance 必须 FAIL；
- `docs/MVP_RUNBOOK.md`；
- `docs/M5D_REAL_VALIDATION_REPORT.md`，真实验证状态仍为 `NOT_RUN`。

### Engineering Hardening 不能证明

- Real Platform Smoke PASS；
- Production AI Provider Validation PASS；
- Full Human-in-loop MVP E2E PASS。

这些真实 Gate 必须在受控本地环境从绿色 exact-head 单独执行。

## M5-D B. Real Platform Smoke

当前：**PENDING / NOT_RUN**。

首选顺序：Bilibili → Zhihu。MVP 只要求至少一个完成低量真实 Smoke，但一平台 Gate 不能宣称七平台 Real-world 全验证完成。

必须使用：

- isolated low-value test account；
- controlled visible Chrome/CDP/profile；
- explicit human confirmation；
- 现有 CollectorRuntime / RawSignal / Checkpoint / CollectionRun 主链；
- 现有 Account/Risk/Budget Guard；
- 默认 search limit=1，且绝不超过现有更严格 gate。

出现 403/406/429、CAPTCHA、automation detection、账号异常、login invalidation、`REVIEW_REQUIRED`、`RESTRICTED` 等风险信号立即停止并记录 `RISK_BLOCKED`/`PRECONDITION_BLOCKED`，不得 retry 到成功、换号或代理绕过。

## M5-D C. Production AI Provider Validation

当前：**PENDING / NOT_TESTED**。

PASS 必须同时具有：

1. production-compatible Provider；
2. 真实 `env://...` credential；
3. 真实 network；
4. Provider Connection Test succeeded；
5. 至少一个正式 AIGateway 业务 Invocation succeeded；
6. structured output schema validation；
7. Invocation / Attempt provenance；
8. AI Budget reservation/settlement；
9. usage/cost 如实 available/unknown；
10. 无 credential 泄漏。

FakeProvider / MockTransport / stub server 永远不能提升本状态。

## M5-D D. Full Human-in-loop MVP E2E

当前：**PENDING / NOT_RUN**。

目标链：

```text
Real Platform Signal
→ MediaCrawler Adapter
→ CollectorRuntime
→ RawSignal / Checkpoint / CollectionRun
→ Event / EventSignal
→ EvidenceClaimSource
→ Trend
→ real Provider Editorial Score
→ Daily Candidate
→ Human Workbench Review
→ Human Adopt
→ Event Card / Editorial Pack
→ real Provider AI Draft
→ read-only verifier PASS
```

Human Adopt 必须由真人执行并存在 actor + reason。脚本不得按 rank 自动 Adopt，也不得自动 confirmed Evidence、创建缺失 Candidate/Card/Pack/Draft 或关闭 Risk/Stale/Citation Gate。

MVP E2E 硬 Gate 到 Draft 即可；不要求真实自动发布。M5-C Publication/Performance 的 optional manual smoke 可使用已有历史发布内容，但不得为了 M5-D 在正式账号主动发布测试内容。

## M5-D MVP Closeout

只有以下全部成立才允许：

```text
M5-D COMPLETE
M5 Overall COMPLETE
```

条件：

- M5-A/B/C COMPLETE / MERGED；
- M5-D Engineering Hardening COMPLETE；
- Real Platform MVP Gate PASSED；
- Production AI Provider Validation PASSED；
- Full Human-in-loop E2E PASSED；
- sanitized validation report；
- final exact-head CI success。

缺任一项：`M5 Overall NOT COMPLETE`。

即使 MVP Closeout 最终完成，也只表示 **MVP Engineering & One-Platform Real E2E Gate COMPLETE**，不表示七平台生产已验证、大规模聚类质量已验证、账号绝对安全、商业 License 已解决或自动发布已完成。

## Engineering Gate

M5-D Phase 1 要求：

```bash
ruff check .
mypy apps packages
pytest
```

并继续执行：

- M3 concurrent reprocess targeted；
- M3 offline engineering evaluation；
- M3 performance baseline；
- Alembic `upgrade head → downgrade -1 → upgrade head → downgrade base → upgrade head`；
- Definition sync ×2，第二次 `created=0 / updated=0 / failed=0`；
- Web `lint / typecheck / test -- --run / build`。

Engineering Hardening 工程 Gate 已全部通过；文档同步后的 final exact-head CI 仍必须保持 Python/Web success，才能对外报告 `AWAITING HUMAN REAL VALIDATION`。

## 当前结论

当前不是 M5-D COMPLETE，也不是 MVP COMPLETE：

```text
M5-C COMPLETE / MERGED
M5-D Engineering Hardening COMPLETE
Real Platform Smoke PENDING / NOT_RUN
Production AI Provider Validation NOT_TESTED / PENDING
Full Human-in-loop MVP E2E PENDING / NOT_RUN
M5 Overall NOT COMPLETE
M2 Real Smoke Validation DEFERRED / NOT_TESTED
M2 Real-world Validation NOT COMPLETE
```

当前阶段仅允许进入 `AWAITING HUMAN REAL VALIDATION`，不代表真实 Gate 已执行。