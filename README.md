# AI Editorial Desk

AI 编辑部系统：面向短视频创作者的多来源信息发现、资料整理、编辑判断与内容生产辅助系统。

**当前工程状态：M1 Engineering COMPLETE；M2 Engineering COMPLETE；M2 Real Smoke Validation = DEFERRED / NOT_TESTED；M2 Real-world Validation = NOT COMPLETE；M3 Overall Engineering COMPLETE；M4 Overall Engineering COMPLETE；M5-A Editorial Workbench COMPLETE / MERGED；M5-B Daily Candidates / Editorial Workflow COMPLETE / MERGED；M5-C Publication / Performance Feedback COMPLETE / MERGED；M5-D Engineering Hardening IN PROGRESS / PR #23 OPEN；Real Platform Smoke PENDING；Production AI Provider Validation = NOT_TESTED；Full Human-in-loop E2E PENDING；M5 Overall = NOT COMPLETE。**

> GitHub CI、Fake Provider、MockTransport、synthetic platform fixture 与 offline E2E 只能证明 Engineering Hardening，不能替代真实平台、真实 Production Provider 或 Human-in-loop E2E 验证。

开发入口见 [`docs/START_HERE.md`](docs/START_HERE.md)，MVP 运行与真实验证步骤见 [`docs/MVP_RUNBOOK.md`](docs/MVP_RUNBOOK.md)，M5-D 脱敏验证报告模板见 [`docs/M5D_REAL_VALIDATION_REPORT.md`](docs/M5D_REAL_VALIDATION_REPORT.md)，阶段验收见 [`docs/M5_ACCEPTANCE_REPORT.md`](docs/M5_ACCEPTANCE_REPORT.md)，架构决定见 [`docs/DECISIONS.md`](docs/DECISIONS.md)。

## 当前处理链

```text
Connector / CollectorRuntime
→ RawSignal / RawSignalComment
→ Event / EventSignal
→ Signal Embedding / Matching / Clustering
→ EvidenceClaim / EvidenceClaimSource / EventUnknown
→ Deterministic Trend Snapshot
→ AIGateway Editorial Scoring
→ Human Manual Score / Override
→ Effective Editorial Assessment
→ Event Card
→ Editorial Pack
→ Evidence-aware Draft / Human Revision
→ Deterministic Markdown Export
→ M5-A Editorial Workbench
→ M5-B Daily Candidates / Editorial Workflow
→ M5-C Publication / Performance Feedback
```

M5-D 不新增新的业务主链，而是为这条既有链增加 Engineering Hardening、真实验证 Preflight/Harness、只读 E2E provenance verifier、秘密脱敏与 MVP Runbook。

## Editorial Workbench / Candidate / Publication

M5-A 是 M1～M4 后台能力的整合层，不重新实现 Event、Evidence、Trend、Score、Card、Pack 或 Draft 业务逻辑。M5-B 在其上增加确定性 Daily Candidate snapshot 与 append-only Human Editorial Decision；M5-C 再记录真实 Publication 与 append-only Performance Feedback。

关键边界：

- Event lifecycle、Algorithmic Rank、Human Decision、Publication、Performance 分层保存；
- Adopt 不等于 Published，Draft 不等于 Published；
- Unknown 不是 Fact，`single_source` 不是 confirmed；
- unavailable feature 为 NULL/Unavailable，不伪装为 0；
- Human Override / Decision / Revision 保持 append-only；
- merged Event 历史 artifact 可读，新写操作遵循 `EVENT_MERGED + target_event_id`；
- AI Score / Draft 只能由用户显式触发；
- R3/R4、stale context、citation、verification 继续由现有 Service/API 强制校验；
- Publication 只记录真实已发布结果，不自动向平台发布；
- Performance 不自动修改 Candidate Rank、Score、Decision、Evidence、Prompt 或模型权重。

## Evidence / Draft 安全语义

Draft 中的事实只能沿目标 Event 内真实 Evidence Claim citation chain：

- confirmed：可 `fact` 或 attributed；
- investigating：必须 attributed；
- single_source：必须 attributed；
- disputed：必须保留 disputed 语义；
- false：只能用于 debunk/fact-check；
- Unknown：只能作为 open question。

Human Draft / Human Revision 使用 append-only version chain，AI 原始版本不会被覆盖。Draft Apply 在 Provider 返回后重新校验 Evidence、Effective Editorial Assessment 与 Event merge 状态；R3/R4 继续受 Risk Gate 约束。

Markdown Export 是 deterministic renderer，不再次调用 AI。

## Admin Token / Sensitive Data

所有写操作继续要求 Admin Token + `X-Actor-ID`。Web 只使用 `sessionStorage` 保存当前会话 Token/Actor。

API/UI/Validation Report 不展示 RawSignal `raw_payload`、credential、Authorization、API Key、Cookie、完整 Prompt、绝对 browser profile 路径或 embedding vector。Provider credential 只能通过受控 opaque ref（例如 `env://OPENAI_API_KEY`）解析。

## AIGateway 边界

Editorial Scoring 与 AI Draft 继续使用既有 `AIGateway.generate_structured(...)`，完整经过 Route / Budget / Retry / Fallback / Schema / Invocation / Attempt / Usage / Cost。Provider 调用位于数据库长事务之外。

M5-D 进一步冻结：

- 注入 ProviderFactory / MockTransport 的 Connection Test 只属于 Engineering Test；
- Fake/Mock 成功不能提升 `Production AI Provider Validation`；
- Production Provider PASS 必须由真实 credential + network 的 Connection Test 与至少一次正式业务 Invocation/Attempt 共同证明；
- usage/cost 不可用时保持 unknown，不能写 0 冒充已知。

## M5-D Engineering Hardening

新增工程入口：

```bash
python -m scripts.mvp_doctor
python -m scripts.m5d_preflight --help
python -m scripts.run_m5d_platform_smoke --help
python -m scripts.run_m5d_provider_validation --help
python -m scripts.verify_m5d_e2e --help
```

其中：

- `mvp_doctor`：read-only PASS/WARN/BLOCK 运行检查；
- `m5d_preflight`：真实 Platform / Provider / E2E 前置条件检查；
- `run_m5d_platform_smoke`：只薄封装既有 M2 MediaCrawler smoke 主链，禁止在 CI 真实运行；
- `run_m5d_provider_validation`：要求 `--confirm-paid-call`，Connection Test 单独成功仍返回 `PENDING_BUSINESS_INVOCATION`；
- `verify_m5d_e2e`：只读验证 CollectionRun→RawSignal→Event→Evidence→Trend→real AI Score→Candidate→Human Adopt→Card/Pack→real AI Draft 同链 provenance，不补建缺失 Artifact。

真实运行细节见 `docs/MVP_RUNBOOK.md`。

## 数据库迁移

M5-D 默认 **NO NEW MIGRATION**。当前 migration head 继续：

`20260810_0015_m5c_publication_performance`

M5-D Harness / Doctor / Verifier / Validation Report 不建立第二套业务真相表。

## Engineering Gate

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

Definition 第二次同步必须 `created=0 / updated=0 / failed=0`；M3 concurrent regression、offline engineering evaluation、performance baseline 继续保留。

## M5-D 真实 Gate

普通 GitHub Actions 不运行真实账号/浏览器或 Production credential。Phase 1 exact-head CI 绿色后，在受控本地同一绿色 HEAD 上执行：

```text
Preflight
→ Human confirm
→ Bilibili（首选）或 Zhihu real low-volume smoke
→ Provider Connection Test
→ real AIGateway business invocation
→ real Event / Evidence / Trend / AI Score
→ Candidate Pool
→ Human Workbench review + Adopt
→ Card / Pack
→ real AI Draft
→ read-only verifier
→ sanitized validation report
```

出现 403/406/429、CAPTCHA、automation detection、account blocked/abnormal、login invalidation、`REVIEW_REQUIRED`、`RESTRICTED` 或现有 Risk Guard stop 条件时立即停止；不 retry 到成功、不换号、不换代理、不重开 Profile 绕过。

## 当前阶段边界

当前只推进 **M5-D Engineering Hardening / PR #23**。在 Real Platform、Production Provider、Human E2E 与 final exact-head CI 全部真实 PASS 前：

```text
M5-D NOT COMPLETE
M5 Overall NOT COMPLETE
M2 Real Smoke Validation DEFERRED / NOT_TESTED
M2 Real-world Validation NOT COMPLETE
Production AI Provider Validation NOT_TESTED
```

不开始 M6/V1，不自动发布，不接平台发布 API；一平台 MVP real gate 也不等于七平台生产验证完成。
