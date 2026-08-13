# M5 Acceptance Report

> Final Status: **M5 Overall COMPLETE**
>
> 本文分别记录 M5 工程阶段与真实验证状态。Engineering CI、Mock/Fake、synthetic fixture 或 offline E2E 不能替代真实平台、Production Provider 或 Human-in-loop E2E；M5-D 最终 PASS 依据真实受控验证与正式 provenance verifier 成立。

## 阶段状态

- **M5-A Editorial Workbench：COMPLETE / MERGED**
- **M5-B Daily Candidates / Editorial Workflow：COMPLETE / MERGED**
- **M5-C Publication / Performance Feedback：COMPLETE / MERGED**
- **M5-D A Engineering Hardening：PASS**
- **M5-D B Real Platform Smoke：PASS（Bilibili low-volume only）**
- **M5-D C Production AI Provider Validation：PASS**
- **M5-D D Full Human-in-loop MVP E2E：PASS**
- **formal `verify_m5d_e2e`：PASS**
- **M5-D Real Validation Report：PASS / CURRENT**
- **PR #23：MERGED**
- **M5 Overall：COMPLETE**

继续保留以下范围边界：

- **M4 Overall Engineering：COMPLETE**；
- **M2 deferred real-smoke Gate for MVP/M5 closeout：SATISFIED / CLOSED by Bilibili low-volume real smoke**；
- **M2 broader real-world platform coverage：PARTIAL**；
- **当前明确单独真实 smoke 证明的平台仅为 Bilibili**；
- 不得写成 `All MediaCrawler platforms have been production validated`。

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

### Manual / CSV / Feedback projection

- Manual Performance 支持核心 metric；
- canonical CSV = `performance-csv-v1`；
- Preview side-effect free；
- Apply 需要 Actor + confirmation；
- ImportRun 保留 CSV provenance；
- Performance Feedback 只读并排展示 Candidate Rank、Human Decision、Score/Risk/Format、Draft version、Publication 与真实指标。

M5-C **不**：

- 自动发布；
- 接平台发布 API；
- 自动改 Candidate Rank；
- 自动改 Editorial Score；
- 自动改 Human Decision；
- 自动改 Evidence verification；
- 自动调 Prompt/weight/model。

V1-D 后续应建立在 M5-C 现有模型之上，重点补真实运营数据与校准分析，不建立第二套 Publication / Performance 模型。

## Migration

M5-C migration：

```text
20260810_0015_m5c_publication_performance
```

M5-D **NO NEW MIGRATION**。Harness/Doctor/Verifier/Report 组合现有 Run/Risk/Checkpoint/Provider/Invocation/Artifact 证据，不新建 Validation 业务真相表。

## M5-D A. Engineering Hardening

**PASS**。

已完成：

- `M5DPreflightService`；
- `MVPDoctorService`；
- `verify_business_invocation`；
- `verify_m5d_e2e`；
- Validation output/report recursive secret redaction；
- MediaCrawler real smoke 薄 wrapper；
- Production Provider validation CLI；
- Fake/Mock validation-status hard gate；
- E2E provenance 防伪回归；
- `docs/MVP_RUNBOOK.md`；
- `docs/M5D_REAL_VALIDATION_REPORT.md`。

这些工程能力不会自动登录、自动采集、自动调用 AI、自动 Adopt、自动补建缺失 Artifact 或自动发布。

## M5-D B. Real Platform Smoke

**PASS**。

真实验证范围：

```text
platform = bilibili
CollectionRun = 19bed81a-ac50-4251-ab57-7eb841a91bfb
RawSignal = f2e03174-3023-4e64-8389-2a8724fabb82
collected / inserted / failed = 1 / 1 / 0
platform risk = none observed
result = real / non-mock
```

该证据满足 D-030 对 MVP Closeout 的 real-platform Gate，并关闭 M2 deferred real-smoke Gate for MVP/M5 closeout。

该证据**不**证明：

- Zhihu 已完成单独 real smoke；
- Weibo 已完成单独 real smoke；
- Douyin / Xiaohongshu / Kuaishou / Baidu Tieba 已完成真实验证；
- 七个平台具备生产规模稳定性。

真实平台仍遵循 isolated low-value test account、visible Chrome/CDP、stable profile、concurrency=1、low-volume 和 risk signal immediate stop。

## M5-D C. Production AI Provider Validation

**PASS**。

Production Provider：

```text
provider = deepseek-production
model = deepseek-v4-flash
```

正式业务 Invocation 已验证：

```text
Evidence Extraction = 943b9268-df55-4eaa-a31a-79f31dafb9ad
Editorial Scoring = e3717ac1-2b03-4d30-85e5-080348752fdf
Draft Generation = 37c7c07f-e0ed-48d9-8758-158754f4ad76
```

这些 invocation 均为正式业务任务、ProviderAttempt succeeded，并通过 `verify_business_invocation`。Mock/Fake 证据没有参与提升真实 Provider 状态。

## M5-D D. Full Human-in-loop MVP E2E

**PASS**。

正式验证链：

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
→ read-only verifier PASS
```

关键 durable provenance：

```text
Event = bbfb5989-0eb3-4bfc-af31-72f907625d28
TrendSnapshot = 1b5840f1-35dc-490d-8d60-20bd8157c3cb
Evidence Extraction Run = 9d32f301-bb04-406c-b390-db7d8f2c578e
Confirmed Claim = c7cafbd6-1c71-4d8a-989c-fa578e642790
EditorialScore = 087592c4-53e4-46a2-a63c-22a98104d9ef
CandidateRun = a70457d0-5fd2-48c8-be6e-2d1873a6d520
Candidate = ee702c9f-778a-4cbd-a8eb-52a0773ecf47
Human Decision = e4b58428-0c88-4224-bea5-5d142e47f98b / adopt / actor chengshier
Card = 827ac0cc-5445-4fad-b8b2-6d80a1811748
Pack = ad010d85-e316-48c4-913a-a4bdcbea7bd0
Draft = c905a3be-a977-45f5-b8e8-1d5699e661c4
```

`verify_m5d_e2e = PASS`。

MVP E2E 硬 Gate 到 Draft；真实 external publication / performance 不属于 M5-D 完成前置条件。

## Evidence / Risk / Structured Output 最终边界

M5-D 真实验证中暴露并修复三类问题：

1. Evidence Extraction output budget：2048 → 4096；
2. Editorial Scoring output budget：1200 → 4096，并让 deterministic guard 与模型 contract 共享 `allowed_risk_levels` / R0 eligibility semantics；
3. Draft 升级为 `draft-generation-v2`，要求 exactly one JSON object、禁止 Markdown/code fence/prose before/after，并继续使用严格 `json.loads` + schema validation。

这些修复不允许在 Post-MVP 中被回退为：

- 两套 risk 规则；
- malformed JSON repair；
- 自动 silent coercion。

AI generation 参数配置化属于 Post-MVP 技术债，不回填为新的 M5 历史开发阶段。

## Engineering / Merge Baseline

M5-D Real Validation Report 记录的验证 engineering head 与当时 exact-head CI 作为真实验证 provenance 保持不变。

PR #23：

```text
feat: 完成 M5-D Hardening与MVP收口
```

已于 2026-08-13 人工合并到 `main`。

Merge commit：

```text
8ab9200172786705f9e73093646e3d3d3507ee2f
```

该 merge commit 的 GitHub Actions：

```text
python = success
web = success
```

## Final Gate Matrix

| Gate | Status |
|---|---|
| M5-A Editorial Workbench | COMPLETE / MERGED |
| M5-B Daily Candidates / Editorial Workflow | COMPLETE / MERGED |
| M5-C Publication / Performance Feedback | COMPLETE / MERGED |
| M5-D A Engineering Hardening | PASS |
| M5-D B Real Platform Smoke | PASS |
| M5-D C Production Provider | PASS |
| M5-D D Human-in-loop E2E | PASS |
| formal `verify_m5d_e2e` | PASS |
| M5-D Real Validation Report | PASS / CURRENT |
| PR #23 | MERGED |
| merge-head Python CI | success |
| merge-head Web CI | success |
| M5-D COMPLETE | YES |
| M5 Overall COMPLETE | YES |

## 当前结论

```text
M5 Overall = COMPLETE
POST-MVP / V1 READINESS = ACTIVE
Next formal product stage = V1-A / V1-B / V1-C / V1-D
There is no M6
```

后续执行与进度统一记录在：

`docs/POST_MVP_V1_READINESS_CHECKLIST.md`

本结论不扩大为全平台真实采集稳定性、大规模长期运行稳定性或自动发布能力已验证。
