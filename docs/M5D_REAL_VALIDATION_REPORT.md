# M5-D Real Validation Report

> Status: **NOT_RUN**
>
> 本文档是 M5-D 真实验证的脱敏证据模板。Engineering CI、Mock Provider、synthetic fixture、offline E2E 都不能把本文档状态自动提升为 PASS。

## 1. Validation Metadata

| Field | Value |
|---|---|
| validation_id | NOT_RUN |
| result | NOT_RUN |
| executed_at | NOT_RUN |
| timezone | NOT_RUN |
| git_head | NOT_RUN |
| environment | local-controlled |
| attempt_count | 0 |

不得记录机器用户名、绝对 Home 路径、IP、Cookie、Authorization、API Key、Provider credential、完整 browser profile 路径或完整 Prompt。

## 2. Engineering Evidence

| Gate | Status | Evidence |
|---|---|---|
| Ruff | NOT_RUN | final exact-head CI required |
| Mypy | NOT_RUN | final exact-head CI required |
| Pytest | NOT_RUN | final exact-head CI required |
| M3 concurrency regression | NOT_RUN | final exact-head CI required |
| M3 offline evaluation | NOT_RUN | final exact-head CI required |
| M3 performance baseline | NOT_RUN | final exact-head CI required |
| Alembic round trip | NOT_RUN | expected head `20260810_0015` |
| Definition sync ×2 | NOT_RUN | second run must be created=0 / updated=0 / failed=0 |
| Web lint/typecheck/test/build | NOT_RUN | final exact-head CI required |

Engineering PASS 只代表 `M5-D Engineering Hardening`，不代表 Real Platform 或 Production Provider。

## 3. Real Platform Smoke

| Field | Value |
|---|---|
| result | NOT_RUN |
| platform | NOT_RUN |
| connector_type | mediacrawler |
| connector_definition_version | NOT_RUN |
| smoke_limit | NOT_RUN |
| collection_run_id | NOT_RUN |
| raw_signal_count | NOT_RUN |
| checkpoint_before | NOT_RUN |
| checkpoint_after | NOT_RUN |
| account_ref_masked | NOT_RUN |
| profile_ref_masked | NOT_RUN |
| risk_result | NOT_RUN |

### Pass conditions

- real network + controlled visible Chrome/CDP/profile；
- isolated low-value test account；
- explicit human confirmation；
- CollectionRun succeeded；
- RawSignal count >= 1；
- Checkpoint semantics correct；
- no Risk Stop event；
- no synthetic/mock data；
- no secret leakage。

### Blocked attempts

真实验证发生 `RISK_BLOCKED` / `PRECONDITION_BLOCKED` 时追加脱敏条目，不删除失败尝试。

| Attempt | Timestamp | Platform | Result | Block reason |
|---|---|---|---|---|
| 1 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |

不要记录帖子正文、评论正文、真实用户昵称、外部账号 ID 或完整 URL 列表。

## 4. Production AI Provider Validation

| Field | Value |
|---|---|
| result | NOT_RUN |
| provider_key | NOT_RUN |
| model_key | NOT_RUN |
| validated_task_keys | NOT_RUN |
| connection_test_invocation_id | NOT_RUN |
| business_invocation_ids | NOT_RUN |
| attempt_status | NOT_RUN |
| usage_status | NOT_RUN |
| cost_status | NOT_RUN |
| validated_at | NOT_RUN |

### Pass conditions

1. 真实 production-compatible Provider 配置；
2. 真实 `env://...` credential；
3. 真实 network；
4. Provider Connection Test succeeded；
5. 至少一个正式 AIGateway 业务 Invocation succeeded；
6. structured output schema validation succeeded；
7. Invocation / Attempt 正确落库；
8. AI Budget reservation / settlement 正常；
9. usage/cost 有值则记录 available，无值记录 unknown；
10. 无 credential 泄漏。

FakeProvider / MockTransport / stub server 不能填写本节 PASS。

## 5. Full Human-in-loop MVP E2E

| Artifact / Gate | Value |
|---|---|
| result | NOT_RUN |
| platform | NOT_RUN |
| collection_run_id | NOT_RUN |
| raw_signal_count | NOT_RUN |
| event_id | NOT_RUN |
| evidence_claim_source_count | NOT_RUN |
| trend_snapshot_id | NOT_RUN |
| editorial_score_id | NOT_RUN |
| score_invocation_id | NOT_RUN |
| candidate_run_id | NOT_RUN |
| algorithmic_rank | NOT_RUN |
| human_decision_id | NOT_RUN |
| card_id | NOT_RUN |
| pack_id | NOT_RUN |
| draft_id | NOT_RUN |
| draft_invocation_id | NOT_RUN |
| risk | NOT_RUN |
| verifier_result | NOT_RUN |

### Required provenance

```text
Real Platform Signal
→ MediaCrawler Adapter
→ CollectorRuntime
→ RawSignal / Checkpoint / CollectionRun
→ Event / EventSignal
→ EvidenceClaimSource
→ Trend
→ real Provider Editorial Score
→ candidate-ranking-v1 Candidate
→ Human Adopt
→ Event Card
→ Editorial Pack
→ real Provider AI Draft
→ M5-D read-only verifier PASS
```

Human Adopt 必须由真实操作者在 Web/API 正式 Human Decision 语义下完成，存在 actor + reason；脚本不能自动生成 Adopt。

## 6. Optional M5-C Manual Smoke

如果操作者已有真实历史发布内容，可以额外验证：

- `manual_backfill` Publication；
- 一条 manual Performance Snapshot。

状态：**NOT_RUN / OPTIONAL**。

不得为了 M5-D 在正式账号主动发布测试内容。

## 7. Final Gate Matrix

| Gate | Status |
|---|---|
| M5-A Editorial Workbench | COMPLETE / MERGED |
| M5-B Daily Candidates / Editorial Workflow | COMPLETE / MERGED |
| M5-C Publication / Performance Feedback | COMPLETE / MERGED |
| M5-D Engineering Hardening | IN_PROGRESS |
| Real Platform MVP Gate | NOT_RUN |
| Production AI Provider Validation | NOT_TESTED |
| Full Human-in-loop E2E | NOT_RUN |
| M5 Overall | NOT COMPLETE |
| M2 Real Smoke Validation | DEFERRED / NOT_TESTED |
| M2 Real-world Validation | NOT COMPLETE |

只有所有 MVP 必需真实 Gate 与 final exact-head CI 都 PASS 后，才允许将：

```text
M5-D COMPLETE
M5 Overall COMPLETE
Production AI Provider Validation PASSED
M2 Real Smoke Validation PASSED (with actual validated platform/scope/limit)
```

即便最终完成，也必须继续保守注明：一平台 MVP Smoke 不等于七平台生产验证；自动发布未实现；大规模聚类质量未验证；MediaCrawler 商业/变现前仍需重新核对许可。
