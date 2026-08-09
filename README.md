# AI Editorial Desk

AI 编辑部系统：面向短视频创作者的多来源信息发现、资料整理、编辑判断与内容生产辅助系统。

**当前工程状态：M1 COMPLETE；M2 Engineering COMPLETE；M2 Real Smoke Validation = DEFERRED / NOT_TESTED；M2 Real-world Validation = NOT COMPLETE；M3 Overall Engineering COMPLETE；M4-A AI Gateway Engineering COMPLETE；M4 Overall NOT COMPLETE。**

> M3-D PR #14 已合并到 `main`。M4-A 当前位于 PR #15 `feature/m4a-ai-gateway`，PR 保持 Open，不自行合并。Production AI Provider Validation 在没有人工生产 credential 与真实网络调用时保持 `NOT_TESTED`，CI Fake/Mock 不能替代真实验证。

开发入口见 [`docs/START_HERE.md`](docs/START_HERE.md)，M3 工程验收见 [`docs/M3_ACCEPTANCE_REPORT.md`](docs/M3_ACCEPTANCE_REPORT.md)，M4-A 工程验收见 [`docs/M4_ACCEPTANCE_REPORT.md`](docs/M4_ACCEPTANCE_REPORT.md)，架构决定见 [`docs/DECISIONS.md`](docs/DECISIONS.md)。M4-A Engineering 完成不会把 M2 Real Smoke 或 Production Provider Validation 改写为 PASSED。

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

Business Task
→ AI Task Route / immutable route version                  M4-A
→ Provider / Model target                                  M4-A
→ AI Gateway                                               M4-A
→ Invocation / Attempt audit                               M4-A
→ Usage / pricing snapshot / estimated cost                M4-A
→ AI Budget reserve / settle                               M4-A
```

采集层与 M3 Processing 层继续解耦：Connector / CollectorRuntime 不同步创建 Event、不等待通用 AI Gateway，也不让 M4-A 改写 M3 clustering 结果。M3-B `EmbeddingProvider` Contract 仍是 Embedding 持久化边界；M4-A 仅通过 `GatewayEmbeddingProvider` 提供生产桥接。

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

## M4-A — AI Gateway / Provider / Route / Cost Governance

- 正式 `ai_providers` / `ai_models` / `ai_task_routes`；业务只引用 `task_key`，不硬编码 Provider URL 或供应商模型名；
- Provider credential 只保存 opaque `credential_ref`；M4-A 提供受控 `env://NAME` resolver，DB/API/Web/日志不保存或回显明文 API Key；
- `AIGateway.embed(...)` / `generate_text(...)` / `generate_structured(...)` 使用领域对象，不把第三方 SDK/HTTP payload 穿透业务层；
- 一个 OpenAI-compatible adapter 同时覆盖可配置云端与显式允许的本地兼容端点；不写死 `api.openai.com` 或商业模型枚举；
- Route 每次修改创建新版本；历史 Invocation 固定记录 `route_version/provider/model`，旧路由不会被当前配置覆盖；
- `ai_invocations` + `ai_invocation_attempts` 记录 input hash、prompt/schema version、usage、latency、retry/fallback、provider request id、pricing snapshot 与错误码，不默认保存完整 Prompt/Body/Embedding；
- bounded retry 只对明确可重试错误执行，fallback 必须显式配置且每个 attempt 可追溯；
- 模型价格来自配置，Invocation 固化 pricing snapshot 与最终 estimated cost；usage/cost 缺失保持 unknown，不伪造 0；
- `ai_budgets` / `ai_budget_usages` 独立于 CollectionBudget，支持 global/task/provider scope，并使用 PostgreSQL 行锁完成调用前 reserve、调用后 settle；
- 最小 Admin API 与 Web 页面覆盖 AI Providers/Models、AI Routes、AI Budgets、AI Invocations；Credential 只允许 replace；
- M3-B 通过 Gateway bridge 获得生产实现，但不重建 `SignalEmbedding`、input builder 或 vector recall，也不自动全库 backfill；
- CI 全部使用 MockTransport/Fake，不访问公网或真实付费 Provider。

## M4-A 范围边界

M4-A 只建立通用 AI 调用基础。当前六个 task key 可注册/配置，但除 `embedding` bridge 外不在本批接入业务逻辑：

```text
embedding
event_boundary_review
evidence_extraction
editorial_scoring
draft_generation
final_review
```

因此：

- M4-B Evidence / Claim：NOT STARTED；
- M4-C Trend / Editorial Score：NOT STARTED；
- M4-D Event Card / Script / Draft：NOT STARTED；
- M5：NOT STARTED；
- M4-A 不修改 M3 Event clustering、evaluation ground truth 或 threshold。

## Migration Head

M4-A 新增：

```text
20260809_0010_m4a_ai_gateway
```

M3 migration：

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
M3 Overall Engineering COMPLETE / PR #14 merged
M4-A AI Gateway Engineering COMPLETE / PR #15 Open
Production AI Provider Validation NOT_TESTED
M4-B NOT STARTED
M4-C NOT STARTED
M4-D NOT STARTED
M4 Overall NOT COMPLETE
M5 NOT STARTED
```

PR #15 必须保持 Open，由人工决定是否合并。后续 M4-B 只能在 PR #15 人工合并后从最新 `main` 创建新的独立分支，不得从 `feature/m4a-ai-gateway` 继续派生。
