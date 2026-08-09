# AI 编辑部项目开发入口

## 当前阶段

```text
M1 COMPLETE / 已合并
M2 Engineering COMPLETE / 已合并
M2 Real Smoke Validation DEFERRED / NOT_TESTED
M2 Real-world Validation NOT COMPLETE
M3-A Event / EventSignal COMPLETE / 已合并
M3-B Embedding / Vector Recall COMPLETE / 已合并
M3-C Dedup / Clustering COMPLETE / PR #13 已合并
M3-D Evaluation / Reprocessing / Closure Engineering COMPLETE / PR #14 Open
M3 Overall Engineering COMPLETE
M4 NOT STARTED
```

当前 M3-D 分支：

```text
feature/m3d-evaluation-closure
```

当前 PR：

```text
#14 feat: 完成 M3-D 聚类评测、重处理与阶段收口
```

PR #14 保持 Open，不自行合并。M4 只有在 PR #14 人工合并后，才能从**最新 `main`** 创建新的独立分支；不得从 M3-D feature branch 继续派生。

M2 Real Smoke Deferred 状态继续保留：进入并完成 M3 Engineering 不等于微博/B站/知乎真实 Smoke 已验证，不得把 NOT_TESTED 改写为 PASSED。

## 必读文档顺序

1. `DECISIONS.md`
2. `M3_ACCEPTANCE_REPORT.md`
3. `M2_ACCEPTANCE_REPORT.md`
4. `M2_REAL_SMOKE_SETUP.md`
5. `AI编辑部_综合开发实施规划_V1.2.md`
6. `AI编辑部_技术开发文档_V1.2.md`
7. `AI编辑部_PRD_V1.2.md`
8. `CHANGELOG.md`
9. `MEDIACRAWLER_LOCAL_CHANGES.md`

冲突优先级继续为：DECISIONS → 综合开发实施规划 → 技术开发文档 → PRD。阶段验收报告记录当前工程事实，但不得覆盖正式架构决策。

## M3 当前正式处理链

```text
RawSignal
→ Event / EventSignal                                  M3-A
→ EmbeddingInput(signal-text-v1)
→ versioned signal_embeddings
→ pgvector exact cosine recall                         M3-B
→ deterministic fingerprint
→ exact / near duplicate
→ event-match-v1
→ automatic Event assignment + human Merge / Split    M3-C
→ offline engineering evaluation
→ convergence / replay / provenance
→ bounded dry-run-first reprocessing                   M3-D
```

Connector / CollectorRuntime 仍停在 RawSignal 边界，不同步进入 Event/Embedding/Clustering 热路径。

## M3-A

已建立：

- `events` / `event_signals`；
- human create / attach / detach；
- PostgreSQL 唯一与并发保护；
- Event 聚合字段与时间语义；
- RawSignal 采集事实不可变边界。

## M3-B

已建立：

- `signal_embeddings` 版本化 artifact；
- `signal-text-v1` input schema；
- EmbeddingProvider contract；
- batch / retry / conflict / vector validation；
- pgvector exact cosine recall；
- embedding version + dimensions 隔离。

当前没有生产云 Provider，也没有通用 AI Gateway。该边界是后续架构决策，不是遗漏：生产 Provider 管理、路由、费用中心和 LLM 能力进入 M4。

## M3-C

PR #13 已合并。已建立：

- `signal_fingerprints`；
- `fingerprint-text-v1 + simhash64-v1`；
- canonical exact duplicate；
- deterministic near duplicate；
- M3-B exact cosine candidate recall reuse；
- `signal_match_decisions`；
- `signal_match_overrides` / `signal_event_suppressions`；
- `event-match-v1` conservative matcher；
- automatic Event assignment；
- Event `related` relation；
- human Merge / Split；
- concurrent assignment protection。

明确没有 MinHash、ANN、Event centroid、LLM event judge。

## M3-D

PR #14 已完成工程实现：

- `m3-clustering-eval-v1` 固定离线评测集；
- deterministic pair precision/recall/F1、coverage/abstention；
- cluster pairwise metrics、overmerge、fragmentation；
- read-only bounded threshold sweep；
- `clustering_processing_runs`；
- immutable `event_assignment_records`；
- Admin evaluate / reprocess preview / confirmed apply API；
- evaluate / reprocess CLI；
- explicit signal IDs 或完整 time range 的 bounded target；
- dry-run-first；
- apply 必须 actor + confirmation；
- human membership / override / suppression 不被自动重处理反转；
- processing-order 与 batch-boundary convergence；
- replay / provenance / versioning / concurrent reprocess tests；
- exact recall + clustering engineering performance baseline。

M3-D 不调用真实平台、真实云 Embedding Provider 或 LLM；不修改 M2 Real Smoke 状态；不进入 M4。

## 当前 Migration

```text
20260808_0006  M3-A Event / EventSignal
20260808_0007  M3-B SignalEmbedding / pgvector
20260808_0008  M3-C Dedup / Clustering
20260808_0009  M3-D Processing / Assignment audit
```

禁止为了收口修改 0001～0008 历史 migration。

## 最终 CI Gate

PR #14 只在**最新 exact-head**同时满足以下条件时具备合并资格：

```bash
ruff check .
mypy apps packages
timeout 90s pytest -q -s tests/test_clustering_reprocess_concurrency_m3d.py
timeout 180s pytest -vv
python -m scripts.evaluate_m3_clustering --format text
pytest -q -s tests/test_clustering_performance_m3d.py
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

CI 不使用真实平台、真实 Cookie、真实云 API Key 或 LLM。

## M3 完成语义

`M3 Overall Engineering COMPLETE` 表示：Event 基础、版本化 Embedding artifact/exact recall、确定性 Dedup/Clustering、人工边界、离线评测、安全重处理与工程回归闭环已经完成。

它**不表示**：

- M2 Real Smoke 已通过；
- 真实云 Embedding Provider 已接入；
- AI Gateway / Provider UI / model routing 已完成；
- LLM 边界判断已启用；
- Evidence / Editorial Scoring 已完成；
- M4 已开始。
