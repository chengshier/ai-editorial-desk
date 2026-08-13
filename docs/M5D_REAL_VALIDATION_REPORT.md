# M5-D Real Validation Report

> Status: **PASS**
>
> 本报告记录受控本地环境中的真实低量验证证据。所有标识符均为持久化业务对象 ID；本文不包含凭据、授权头、外部响应正文或推理正文。

## 1. Validation Metadata

| Field | Value |
|---|---|
| validation_id | m5d-real-e2e-bilibili-deepseek-v1 |
| result | PASS |
| engineering git head | `112cea5948e57e06c90aba4b1317c2581f48708b` |
| engineering CI | GitHub Actions `31662846194`: Python success; Web success |
| environment | local-controlled production-provider validation |
| real platform scope | Bilibili low-volume smoke only |

## 2. M5-D A — Engineering Hardening

**M5D_A_HARDENING = PASS**

| Gate | Status | Evidence |
|---|---|---|
| Ruff | PASS | full repository gate |
| Mypy | PASS | `apps` and `packages` gate |
| Python pytest | PASS | latest full local validation: 579 passed |
| M3 concurrent reprocess | PASS | required targeted engineering gate |
| M3 offline evaluation | PASS | required offline engineering gate |
| M3 performance baseline | PASS | required baseline gate |
| Alembic round trip | PASS | five-step round trip; final head `20260810_0015` |
| Connector Definition Sync ×2 | PASS | second run: created=0, updated=0, failed=0 |
| Web lint / typecheck / tests / build | PASS | full Web gate |
| exact-head CI | PASS | `31662846194`, Python and Web both success |

## 3. M5-D B — Real Platform Smoke

**M5D_B_REAL_PLATFORM_SMOKE = PASS**

| Field | Value |
|---|---|
| platform | bilibili |
| CollectionRun | `19bed81a-ac50-4251-ab57-7eb841a91bfb` |
| RawSignal | `f2e03174-3023-4e64-8389-2a8724fabb82` |
| source URL | `https://www.bilibili.com/video/av116227955497963` |
| result | real, non-mock, successful durable collection |
| collected / inserted / failed | 1 / 1 / 0 |
| platform risk | none observed |

该证据只证明 Bilibili 的低量真实 smoke；不代表七个平台均已验证，也不代表大规模稳定性结论。

## 4. M5-D C — Production Provider Validation

**M5D_C_PRODUCTION_PROVIDER = PASS**

| Field | Value |
|---|---|
| provider | `deepseek-production` |
| model | `deepseek-v4-flash` |
| existing Connection Test | `fcbbb5c3-7920-444e-af4e-8617bea3d553`, succeeded |
| Connection Test rerun for closeout | NO |
| Evidence Extraction business invocation | `943b9268-df55-4eaa-a31a-79f31dafb9ad` |
| Editorial Scoring business invocation | `e3717ac1-2b03-4d30-85e5-080348752fdf` |
| Draft Generation business invocation | `37c7c07f-e0ed-48d9-8758-158754f4ad76` |

上述业务 invocation 均为正式业务任务：`metadata.test = false`、ProviderAttempt succeeded，且 `verify_business_invocation` 的只读验证为 PASS。本文不重复 Connection Test。

## 5. M5-D D — Full Human-in-loop MVP E2E

**M5D_D_HUMAN_IN_LOOP_E2E = PASS**

| Artifact | Durable ID / result |
|---|---|
| CollectionRun | `19bed81a-ac50-4251-ab57-7eb841a91bfb` |
| RawSignal | `f2e03174-3023-4e64-8389-2a8724fabb82` |
| Event | `bbfb5989-0eb3-4bfc-af31-72f907625d28` |
| TrendSnapshot | `1b5840f1-35dc-490d-8d60-20bd8157c3cb` |
| Evidence Extraction Run | `9d32f301-bb04-406c-b390-db7d8f2c578e` |
| Confirmed Claim | `c7cafbd6-1c71-4d8a-989c-fa578e642790` |
| Open Unknown | `b053e35f-c309-4ca9-bc65-151b9e394722` (open) |
| EditorialScore | `087592c4-53e4-46a2-a63c-22a98104d9ef`; risk `R1`; format `quick_explainer` |
| CandidateRun | `a70457d0-5fd2-48c8-be6e-2d1873a6d520` |
| Candidate | `ee702c9f-778a-4cbd-a8eb-52a0773ecf47` |
| Human Decision | `e4b58428-0c88-4224-bea5-5d142e47f98b`; `adopt`; actor `chengshier` |
| Card | `827ac0cc-5445-4fad-b8b2-6d80a1811748` |
| Pack | `ad010d85-e316-48c4-913a-a4bdcbea7bd0` |
| Draft | `c905a3be-a977-45f5-b8e8-1d5699e661c4`; type `short_30s`; prompt `draft-generation-v2` |
| Draft Run | `dfa17fa0-2957-4cfd-a655-ea8806c3f69a` |
| formal verifier | `verify_m5d_e2e = PASS` |

已由正式只读 verifier 验证以下 durable graph：

```text
CollectionRun → RawSignal → Event → EvidenceClaimSource → TrendSnapshot
→ EditorialScore → Candidate → Human Adopt → Card / Pack → Draft
```

其中 Score 与 Draft 均可追溯至真实 production Provider invocation；Claim 通过 EvidenceClaimSource 可追溯至本次真实 RawSignal。

### Evidence boundary

Confirmed Claim 的事实边界仅为：“**视频简介声称**将串联 LLM、Token、Context、Prompt、Tool、MCP、Agent、Agent Skill 等概念，并带观众打通 AI 底层逻辑。”这不确认视频实际逐一解释了这些概念，也不确认视频实际实现了该效果。Open Unknown 保持 `open`。

| Draft evidence-boundary check | Result |
|---|---|
| DESCRIPTION_CLAIM_CORRECTLY_ATTRIBUTED | YES |
| ASSERTS_UNKNOWN_AS_FACT | NO |
| FABRICATED_TRANSCRIPT | NO |
| FABRICATED_UNSOURCED_VIDEO_CONTENT | NO |
| OPEN_UNKNOWN_BOUNDARY_PRESERVED | YES |
| UNSOURCED_CONFIRMED_FACTS | NO |
| CLAIM_REFERENCES_VALID | YES |

## 6. Important Failure Paths and Hardenings

失败记录均保留在 durable state 中；以下修复未重写历史结果，也未降低 schema、evidence 或 risk guard。

1. **Evidence Extraction** — Run `bf0ae3b4-a7da-488b-9f99-b0a401dae368` failed with `STRUCTURED_OUTPUT_INVALID`。取证证明 2048 completion budget 发生 truncation；将 Evidence Extraction output budget 提升至 4096 后，最终真实验证 PASS。
2. **Editorial Scoring** — 曾出现 structured-output truncation，以及模型 `R0` 与确定性 Evidence guard 的冲突。修复包括 scoring output budget 提升至 4096、共享 `allowed_editorial_risk_levels`、在 scoring input 中提供允许风险等级，并让 Prompt 与后端 guard 对齐；不做 silent coercion。最终真实 Score 为 `R1`，验证 PASS。
3. **Draft Generation** — Run `7d01c69e-5c44-414f-bb88-d0923c88e68e` failed with `STRUCTURED_OUTPUT_INVALID`。这不是 truncation：`finish_reason=stop`、output tokens=1535、max=6000。修复为 `draft-generation-v2`，明确要求单一完整 JSON object、禁止 Markdown/code fence/prose，并要求严格 schema contract。通用 parser 保持严格 `json.loads`，未放宽解析规则；第二次真实 Draft PASS。

## 7. Publication and Performance Scope

| Item | M5-D closeout requirement | Current result |
|---|---|---|
| External publication | NOT_REQUIRED_FOR_M5D_COMPLETE | NOT_REQUIRED / optional manual smoke |
| Publication manual backfill | NOT_REQUIRED_FOR_M5D_COMPLETE | NOT_REQUIRED / optional manual smoke |
| Real Performance data | NOT_REQUIRED_FOR_M5D_COMPLETE | NOT_REQUIRED / optional manual smoke |

依据 M5 acceptance 与 MVP Runbook，MVP E2E 的硬 Gate 到 Draft 即可；不得为了 M5-D 在真实外部账号主动发布测试内容。未执行项没有被标记为 PASS。

## 8. Final Gate Matrix

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
| Engineering exact-head CI | PASS (`112cea5948e57e06c90aba4b1317c2581f48708b`; `31662846194`) |
| M5-D Real Validation Report | CURRENT |
| M5-D COMPLETE | YES |
| M5 Overall COMPLETE | YES |

本结论不扩大为全平台真实采集稳定性或大规模运营稳定性结论。

## 9. Post-merge Note — 2026-08-13

PR #23 `feat: 完成 M5-D Hardening与MVP收口` 已由真人合并到 `main`。

```text
merge commit = 8ab9200172786705f9e73093646e3d3d3507ee2f
merge-head GitHub Actions python = success
merge-head GitHub Actions web = success
```

本节只补充合并后仓库状态；第 1 节中的 validation engineering head 与 CI、真实业务 Invocation、CollectionRun、RawSignal 和其余 durable provenance 均保持原始真实验证记录，不因后续 merge/release baseline 而改写。

后续路线进入 Post-MVP / V1 readiness；不存在 M6。进度见 `docs/POST_MVP_V1_READINESS_CHECKLIST.md`。
