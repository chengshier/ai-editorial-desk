# AI Editorial Desk

AI 编辑部系统：面向短视频创作者的多来源信息发现、资料整理、编辑判断与内容生产辅助系统。

**当前工程状态：M1 COMPLETE；M2 Engineering COMPLETE；M2 Real Smoke Validation = DEFERRED / NOT_TESTED；M2 Real-world Validation = NOT COMPLETE；M3-A / M3-B / M3-C COMPLETE；M3-D Engineering COMPLETE；M3 Overall Engineering COMPLETE。**

> M3-D 当前位于 PR #14 `feature/m3d-evaluation-closure`。PR 保持 Open，不自行合并；M4 尚未开始。M3 的最终合并准入以 PR #14 最新 exact-head GitHub Actions 全绿为准。

开发入口见 [`docs/START_HERE.md`](docs/START_HERE.md)，M3 工程验收见 [`docs/M3_ACCEPTANCE_REPORT.md`](docs/M3_ACCEPTANCE_REPORT.md)，架构决定见 [`docs/DECISIONS.md`](docs/DECISIONS.md)。M3 Engineering 完成不会把 M2 真实平台 Smoke 改写为 PASSED。

## 当前处理链

```text
Connector Definition / Source / Schedule
→ CollectionTask / CollectorRuntime
→ Budget + Risk Guard + Run
→ RSS / Manual URL / Hotlist / MediaCrawler Adapter
→ Platform Mapper
→ RawSignal / RawSignalComment
→ Checkpoint / Incremental / Resume

RawSignal
→ Event / EventSignal                                      M3-A
→ EmbeddingInput(signal-text-v1) / versioned Embedding     M3-B
→ pgvector exact cosine candidate recall                   M3-B
→ deterministic fingerprint / exact + near duplicate       M3-C
→ event-match-v1 / Event assignment / Merge / Split        M3-C
→ offline evaluation / convergence / bounded reprocessing  M3-D
→ processing + assignment provenance                       M3-D
```

采集层与 M3 Processing 层继续解耦：Connector / CollectorRuntime 不同步创建 Event、不生成 Embedding、不等待 Provider，也不负责事件边界判断。

## M3 工程能力

### M3-A — Event / EventSignal

- 正式 `events` / `event_signals`；
- 人工 create / attach / detach；
- PostgreSQL 唯一约束与并发保护；
- `source_count / platform_count / first_seen_at / last_updated_at` 明确语义；
- RawSignal 采集事实保持不可变。

### M3-B — Embedding / Vector Recall

- `signal_embeddings` 作为可重建、版本化派生 artifact；
- `signal-text-v1` 确定性输入与 `input_hash`；
- EmbeddingProvider contract、受控 batch、有限 retry 与 version conflict；
- pgvector exact cosine recall，按 `embedding_version + dimensions` 隔离；
- 不建立 HNSW / IVFFlat，不将 Fake Provider 注册到生产。

### M3-C — Dedup / Event Clustering

- `fingerprint-text-v1 + simhash64-v1`；
- canonical exact duplicate + deterministic SimHash near duplicate；
- 严格复用 M3-B exact cosine recall；
- 不可变 `signal_match_decisions` 与 `event-match-v1` conservative policy；
- 自动 Event assignment、中性 `related` 关系；
- 人工 override / suppression、Merge / Split；
- RawSignal `FOR UPDATE` + write-time membership recheck 保护并发 assignment。

### M3-D — Evaluation / Reprocessing / Closure

- 固定 `m3-clustering-eval-v1` synthetic/manual 工程评测集；
- deterministic pair / cluster metrics、abstention、overmerge、fragmentation；
- bounded threshold sweep，仅评测，不静默修改生产 policy；
- `clustering_processing_runs` 与不可变 `event_assignment_records`；
- bounded、dry-run-first reprocessing，apply 需要 actor + explicit confirmation；
- 人工 membership / distinct override / event suppression 优先保护；
- processing-order、batch-boundary convergence 与 replay/provenance/concurrency 回归；
- exact recall + clustering 工程性能基线；
- Admin evaluate/reprocess API 与 CLI。

## M3 与原 V1.2 路线的边界

`docs/AI编辑部_综合开发实施规划_V1.2.md` 的早期 M3 描述包含生产云 Embedding Provider、Provider 配置页面、模型路由和 LLM 边界判断。后续架构决策已将这些通用 Provider / Routing / LLM 能力后移到 M4：M3 只冻结可替换的 Embedding Provider contract、版本化 artifact、exact recall、确定性聚类和人工边界，不为了完成阶段而接入真实云 Key 或 LLM。

因此这里的 **M3 Overall Engineering COMPLETE** 指当前决策下的 M3 工程闭环，不代表 M4 AI Gateway / Evidence / Editorial Scoring 已完成，也不代表 M2 Real-world Validation 已完成。

## Migration Head

M3-D 新增：

```text
20260808_0009_m3d_processing_audit
```

历史 M3 migration：

```text
0006 Event / EventSignal
0007 SignalEmbedding / pgvector
0008 Dedup / Clustering
0009 Evaluation / Reprocessing provenance audit
```

## CI Gate

```bash
ruff check .
mypy apps packages
pytest
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

## 当前阶段边界

```text
M1 COMPLETE
M2 Engineering COMPLETE
M2 Real Smoke Validation DEFERRED / NOT_TESTED
M2 Real-world Validation NOT COMPLETE
M3-A COMPLETE
M3-B COMPLETE
M3-C COMPLETE / merged via PR #13
M3-D Engineering COMPLETE / PR #14 Open
M3 Overall Engineering COMPLETE
M4 NOT STARTED
```

PR #14 必须由人工决定是否合并。合并后如果进入 M4，必须从最新 `main` 创建新的独立分支，不得从 `feature/m3d-evaluation-closure` 继续派生。
