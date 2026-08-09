# M3 工程验收报告

## 1. 当前结论

```text
M3-A Event / EventSignal: COMPLETE
M3-B Embedding / Vector Recall: COMPLETE
M3-C Dedup / Clustering: COMPLETE / PR #13 MERGED
M3-D Evaluation / Reprocessing / Closure: ENGINEERING COMPLETE / PR #14 OPEN
M3 Overall: ENGINEERING COMPLETE
M4: NOT STARTED
```

M2 状态保持不变：

```text
M2 Engineering: COMPLETE
M2 Real Smoke Validation: DEFERRED / NOT_TESTED
M2 Real-world Validation: NOT COMPLETE
```

本报告中的 M3 COMPLETE 只表示当前架构决策下的**工程闭环完成**，不代表真实平台验证、M4 AI 能力或 Production Validation 完成。

---

## 2. 阶段基线与分支规则

- M3-A、M3-B 已分别完成并合并；
- M3-C PR #13 `feat: 完成 M3-C 去重与事件聚类基础` 已合并；
- M3-C 最终 feature HEAD：`2aa8e1907d4fc1b4e6be04cb8312a5f2b431cfe1`；
- M3-C merge commit：`87008a560ac248d179332d8b62e46fcd052d3236`；
- M3-D 从该合并后的最新 `main` 独立创建 `feature/m3d-evaluation-closure`；
- M3-D PR #14 保持 Open，不自行合并；
- M4 未开始；如果进入 M4，必须在 PR #14 人工合并后从最新 `main` 独立创建新分支。

---

## 3. M3-A — Event / EventSignal

M3-A 建立正式事件层：

- `events` / `event_signals`；
- human create / attach / detach；
- EventSignal PostgreSQL UNIQUE / FK / CHECK 与并发幂等；
- `source_count`、`platform_count` 从真实关联重算；
- `first_seen_at` 使用 Signal 有效时间；
- `last_updated_at` 只在有效 Event 业务变更时推进；
- RawSignal 采集事实不被事件操作修改。

Migration：`20260808_0006_m3a_event_foundation.py`。

---

## 4. M3-B — Versioned Embedding / Exact Recall

M3-B 将 Embedding 定义为 RawSignal 之上的可重建、版本化派生 artifact：

```text
signal_embeddings
UNIQUE(signal_id, embedding_version)
```

完成：

- `signal-text-v1` 确定性 title/text 输入；
- Provider 输入 SHA-256 `input_hash`；
- EmbeddingProvider Protocol；
- batch、有限 retry、空文本 skip、错误向量拒绝；
- version conflict 防止 silent overwrite；
- dimensionless `VECTOR()` + 独立 dimensions；
- PostgreSQL exact cosine recall；
- recall 只比较相同 `embedding_version + dimensions`；
- Admin metadata / recall 安全输出。

Migration：`20260808_0007_m3b_signal_embeddings.py`。

M3-B 没有生产 Fake Provider，也没有为了阶段验收接入真实云 Key。

---

## 5. M3-C — Dedup / Event Clustering

PR #13 已合并，正式链路：

```text
RawSignal
→ deterministic Fingerprint
→ Exact / Near Duplicate
→ M3-B Exact Cosine Candidate Recall
→ immutable Match Decision
→ Event Assignment
→ Event Cluster
```

核心能力：

- 版本化 `signal_fingerprints`；
- `fingerprint-text-v1 + simhash64-v1`；
- exact duplicate 复用 canonical URL / content hash / platform + external ID；
- near duplicate 使用 deterministic 64-bit SimHash；
- semantic candidate 严格复用 M3-B `SignalSimilarityService`，没有第二套 vector recall；
- `signal_match_decisions` 保存 canonical pair + algorithm version 的不可变判断；
- `event-match-v1` 集中定义 conservative policy；
- `signal_match_overrides` 保存人工 same/distinct 边界；
- `signal_event_suppressions` 防止人工 detach/split 被自动重挂；
- 自动 Event assignment 使用中性 `related`，不伪造 origin/report/reaction；
- Event Merge 保留 source Event，并使用 `merged_into_event_id`；
- Split 写人工 distinct override + suppression；
- same Signal 并发 worker 使用 RawSignal `FOR UPDATE` + write-time membership recheck；
- Preview side-effect free；Batch 只处理显式 bounded signal IDs。

Migration：`20260808_0008_m3c_dedup_clustering.py`。

明确未实现：MinHash、HNSW/IVFFlat、Event centroid、LLM event judge。

---

## 6. M3-D — Offline Evaluation

固定评测版本：

```text
m3-clustering-eval-v1
```

评测集包含 synthetic/manual 工程样本，并显式表达：

- same event；
- distinct event；
- ambiguous；
- expected cluster key；
- expected unassigned；
- human override。

`ClusteringEvaluationService` 提供 deterministic：

- pair precision / recall / F1；
- coverage / abstention rate；
- ground-truth ambiguous 与模型 abstention；
- cluster pairwise precision / recall / F1；
- overmerge count；
- fragmentation count；
- unassigned / auto-created / auto-attached counters；
- evaluation performance metadata。

Ambiguous 被作为显式 abstention 统计，不通过强行归类制造虚假准确率。

### Threshold sweep

阈值 sweep 只在固定小范围 candidate policy 上离线比较：

- SimHash duplicate distance；
- Embedding same-event threshold；
- Embedding distinct threshold；
- ambiguous margin；
- max time gap。

Sweep 是 read-only engineering evaluation：不会修改 `DEFAULT_CLUSTER_POLICY`，不会自动把“最优参数”写回生产配置。

---

## 7. M3-D — Safe Reprocessing

新增 `ClusteringReprocessService`：

- 必须且只能指定 `signal_ids` 或完整 time range；
- `max_items` 有上限；
- algorithm version 必须是当前注册 policy；
- 默认 dry-run；
- apply 必须有 actor 且显式 confirmation；
- deterministic target ordering；
- 不自动全表无限重跑；
- 不执行 automatic detach。

人工状态优先级：

- human membership → `SKIPPED_HUMAN`；
- active event suppression → `SUPPRESSED`；
- human distinct override conflict → `AMBIGUOUS`；
- multiple active memberships / multiple candidate events → `AMBIGUOUS`；
- apply 前重新锁定并检查 membership / Event / suppression / override。

因此重处理不能把已经保存的人工边界静默反转。

---

## 8. Processing / Assignment Provenance

Migration `20260808_0009_m3d_processing_audit.py` 新增：

```text
clustering_processing_runs
event_assignment_records
```

`clustering_processing_runs` 记录：

- evaluate / dry_run / apply mode；
- algorithm / dataset version；
- actor；
- requested / processed count；
- counters；
- config snapshot；
- status / error summary / timestamps。

`event_assignment_records` 是 append-only assignment provenance，记录：

- signal / event；
- create_event / attach / move / detach / conflict action vocabulary；
- attached_by；
- algorithm version；
- match decision；
- processing run；
- previous event；
- created time。

现有 human membership 和历史 configuration audit 可作为兼容 provenance fallback；M3-D 不改写历史 M3-A/M3-C 数据来伪造 provenance。

---

## 9. Convergence / Replay / Concurrency

PostgreSQL 回归覆盖：

- processing order 前向/反向归一化 partition 一致；
- batch size 边界收敛；
- ambiguous signal 保持未强制归类；
- human membership 保留；
- split/detach suppression 保留；
- human distinct override 不被 reprocess 反转；
- version mismatch 明确拒绝；
- replay / provenance 可追溯；
- concurrent reprocess 不产生双重错误归属；
- RawSignal 采集事实边界继续保持。

归一化 partition 使用逻辑成员集合比较，不把随机 Event UUID 当作聚类正确性的依据。

---

## 10. Engineering Performance Baseline

M3-D 建立固定小数据集 PostgreSQL engineering baseline：

- 20 个 Signal；
- 4 维固定测试向量；
- 10 次 exact recall query；
- `top_k=20`；
- exact recall 期望每次返回其余 19 个 candidate；
- 随后执行 20 个 Signal 的 bounded clustering batch；
- 输出 recall / clustering elapsed milliseconds 作为工程基线；
- 不把共享 GitHub Runner 的绝对毫秒数伪装成生产 SLA。

当前仍没有规模证据要求 HNSW / IVFFlat，因此 M3 不提前引入 ANN。

---

## 11. Admin API / CLI

新增/完成：

```text
POST /api/v1/admin/clustering/evaluate
POST /api/v1/admin/clustering/reprocess/preview
POST /api/v1/admin/clustering/reprocess
```

- evaluate 只允许已注册 dataset + algorithm version；
- preview 为 bounded dry-run，不写 Event 业务状态；
- apply 继续使用 Admin Token，并要求 `X-Actor-ID` + request confirmation；
- API 不返回 raw_payload、完整 vector、Cookie、credential 或真实 Provider Key。

CLI：

```text
python -m scripts.evaluate_m3_clustering
python -m scripts.reprocess_m3_clusters
```

---

## 12. 与 V1.2 原 M3 描述的差异

早期 `AI编辑部_综合开发实施规划_V1.2.md` 的 M3 还列出：

- 云 Embedding Provider；
- Provider 配置/连接测试页面；
- Embedding 路由与本地备用；
- LLM 边界判断；
- Embedding 成本统计。

后续 `DECISIONS.md` 的 M3-B 架构决策已把通用 Provider / Model Routing / LLM 能力后移到 M4，并要求 M3 不为了阶段通过而引入真实云 Key、生产 Fake Provider 或第二套 AI Gateway。

因此当前验收口径为：

```text
M3 = Event foundation
   + versioned Embedding artifact / Provider contract / exact recall
   + deterministic dedup / clustering / human boundaries
   + offline evaluation / safe reprocessing / provenance / convergence
```

生产云 Provider、Provider UI、路由、成本中心和 LLM event judge 属于 M4，不作为当前 M3 Engineering Gate 的伪缺口，也不在 PR #14 中提前实现。

---

## 13. CI Gate

M3-D 最终 merge gate 必须由 PR #14 **latest exact-head** GitHub Actions 证明，而不是旧 commit 或本地猜测。

Python Gate：

```text
Ruff
mypy
M3 concurrent reprocess targeted
full pytest
M3 offline engineering evaluation
M3 exact recall + clustering performance baseline
Alembic upgrade head
Alembic downgrade -1
Alembic upgrade head
Alembic downgrade base
Alembic upgrade head
Connector Definition sync
Connector Definition sync again / idempotent
```

Web Gate：

```text
lint
typecheck
unit tests
production build
```

所有上述步骤必须 success，PR #14 才具备人工合并条件。

---

## 14. 明确未进入的范围

M3-D 未实现、未调用：

- 真实平台 Smoke；
- 真实云 Embedding Provider；
- LLM；
- AI Gateway；
- Provider UI / task routing / cost center；
- HNSW / IVFFlat；
- MinHash；
- Event centroid；
- Evidence / Editorial Scoring；
- Trend / velocity / information-gap engine；
- M4/M5 业务。

## 15. 阶段准入结论

在 PR #14 latest exact-head CI `completed/success` 后：

```text
M3 Overall Engineering COMPLETE
PR #14 = MERGEABLE BY HUMAN
M4 = NOT STARTED
```

PR #14 不自行合并。只有人工合并完成后，才能从最新 `main` 创建 M4 独立分支。
