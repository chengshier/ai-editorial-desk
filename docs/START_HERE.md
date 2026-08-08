# AI 编辑部项目开发入口

## 当前阶段

```text
M1 COMPLETE / 已合并
M2 Engineering COMPLETE / 已合并
M2 Real Smoke Validation DEFERRED / NOT_TESTED
M2 Real-world Validation NOT COMPLETE
M3-A Event / EventSignal COMPLETE / 已合并
M3-B Embedding / Vector Recall Engineering COMPLETE / PR #12 Open
M3-C Dedup / Clustering NOT STARTED
M3-D NOT STARTED
M3 Overall NOT COMPLETE
```

当前 M3-B 分支：

```text
feature/m3b-embedding-recall
```

当前 PR：

```text
#12 feat: 完成 M3-B Embedding与向量召回基础
```

PR #12 保持 Open，不自行合并。M3-C 只有在 PR #12 合并后才能从**最新 `main`** 创建独立分支，不得从 `feature/m3b-embedding-recall` 继续派生。

M2 Real Smoke Deferred 状态继续保留：当前 B站 / 知乎 / 微博真实 Smoke 与 Validation 都不是 PASSED；进入 M3 Engineering 不等于 M2 Real-world Validation 已完成。

## 必读文档顺序

1. `DECISIONS.md`
2. `M3_ACCEPTANCE_REPORT.md`
3. `M2_ACCEPTANCE_REPORT.md`
4. `M2_REAL_SMOKE_SETUP.md`
5. `M1_ACCEPTANCE_REPORT.md`
6. `AI编辑部_综合开发实施规划_V1.2.md`
7. `AI编辑部_技术开发文档_V1.2.md`
8. `AI编辑部_PRD_V1.2.md`
9. `CHANGELOG.md`
10. `MEDIACRAWLER_LOCAL_CHANGES.md`

冲突优先级：DECISIONS → 综合开发实施规划 → 技术开发文档 → PRD。阶段验收报告记录当前工程事实，但不得覆盖正式架构决策。

## 已完成工程基线

M1 / M2 已建立采集、Runtime、Budget、Risk、Checkpoint、Scheduler、七平台 MediaCrawler Adapter/Mapper、评论持久化、Profile/Signature/Risk 增强与离线 Smoke readiness。MediaCrawler 继续保持 `third_party` 边界，不因 M3 Processing 改造而进入 Event/Embedding 热路径。

M3-A 已建立：

- `events` / `event_signals`；
- Event / EventSignal Repository / Service；
- human attach / detach；
- `UNIQUE(event_id, signal_id)` 并发保护；
- `source_count / platform_count` 真实关系重算；
- `first_seen_at / last_updated_at` 明确时间语义；
- RawSignal 派生层边界。

## M3-B 正式处理链

```text
RawSignal
→ EmbeddingInputBuilder(signal-text-v1)
→ EmbeddingProvider Contract
→ signal_embeddings
→ pgvector exact cosine recall
→ candidate signals only
```

M3-B **不**判断两个 Signal 是否属于同一 Event。Recall 只是候选召回，M3-C 才消费候选执行 Dedup / Clustering。

## SignalEmbedding

正式表：

```text
signal_embeddings
```

正式字段：

```text
id
signal_id
provider_key
model_name
dimensions
embedding_version
input_schema_version
input_hash
embedding
created_at
```

Embedding 是 RawSignal 的可重建派生 artifact，不把单版本 vector 写回 `raw_signals`。RawSignal 的采集事实字段不因生成、跳过、失败或 Recall 被修改。

### 唯一性

```text
UNIQUE(signal_id, embedding_version)
```

同一 Signal 的不同 embedding version 可以并存；模型升级、Provider/model 配置变化、输入 schema/preprocessing 变化或维度变化必须产生新 `embedding_version`，不得覆盖历史向量。

重复处理语义：

- 同 signal/version 且 input/provider/model/dimension 语义一致：幂等 skip；
- 同 signal/version 但 `input_hash` 或上述配置语义不同：`EMBEDDING_VERSION_CONFLICT`；
- PostgreSQL `UNIQUE + ON CONFLICT DO NOTHING` 是并发最终保护，不只依赖 `SELECT → INSERT`。

## Input Schema

当前 schema：

```text
signal-text-v1
```

确定性输入只来自：

```text
RawSignal.title
RawSignal.text
```

空白统一压缩，最终 Provider 文本稳定；不加入 metrics、raw_payload、Cookie、credential、connector config 或 URL。title/text 都为空时返回 `NO_EMBEDDABLE_TEXT`，不 embed 空字符串或 URL。

最终 Provider 输入文本计算 SHA-256 保存到：

```text
input_hash
```

## Provider Contract

`packages/embeddings/providers.py` 只定义 Embedding 专用 Protocol：

```text
provider_key
model_name
embedding_version
dimensions
batch inputs
vectors
optional usage metadata
optional latency/error metadata
```

当前没有真实云 Provider，也没有生产默认 Fake Provider。测试 Fake/Deterministic Provider 只位于 `tests/`。

M3-B 不实现：

- Chat Completion；
- OpenAI / Anthropic / Gemini / Ollama production adapter；
- Prompt Registry；
- 通用 AI Gateway；
- Token Cost Center；
- 多模型 fallback/router。

## Batch Processor

`EmbeddingBatchProcessor`：

- signal IDs 去重；
- `batch_size` 显式可配置，当前保护范围 1–1000；
- 不一次加载整张 RawSignal 表；
- Provider 网络/模型调用不占用数据库长事务；
- 已有相同 artifact 直接 skip；
- 空文本 skip；
- Provider wrong result count 整个 pending chunk 失败，不静默错位；
- dimensions mismatch、空向量、NaN、Infinity、zero vector 拒绝入库；
- retry 默认 1 次，最多 3 次，不无限 retry；
- 返回 generated / skipped / failed counters 和逐项 code；
- 日志记录 provider/model/version/dimensions/batch/counters/latency，不记录完整 vector、API Key 或完整正文。

## pgvector / Vector Dimension

M3-B 正式增加 Python `pgvector` dependency。

Migration `20260808_0007` 负责：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Downgrade 不执行 `DROP EXTENSION vector`，因为 extension 是共享数据库能力。

向量列使用：

```text
dimensionless VECTOR()
```

不硬编码 1536 / 3072 / 768。每条 artifact 额外保存 `dimensions`，PostgreSQL CHECK：

```text
dimensions > 0
vector_dims(embedding) = dimensions
vector_norm(embedding) > 0
```

应用层同时拒绝空向量、长度错误、NaN、Infinity 和 zero vector。

## Exact Similarity Recall

当前只实现 PostgreSQL exact cosine recall。

输入：

```text
signal_id
embedding_version
top_k
optional min_similarity
optional time_from / time_to
```

只比较：

```text
same embedding_version
same dimensions
```

并排除 target signal 自身。

统一相似度语义：

```text
similarity = 1 - cosine_distance
```

similarity 越大越相似。

返回：

```text
candidate_signal_id
similarity
embedding_version
published_at
collected_at
platform
source_id
```

不返回 `raw_payload` 或完整 vector。

## ANN 决策

M3-B 不建立 HNSW / IVFFlat。

原因：当前阶段优先验证 versioning、dimension isolation、exact cosine correctness；尚无数据规模证据证明 exact search 不可接受。ANN 索引和参数调优后置到有真实规模依据的性能阶段，不为“看起来高级”提前增加运维与版本复杂度。

## Admin API

```text
GET  /api/v1/admin/embeddings/signals/{signal_id}
POST /api/v1/admin/embeddings/recall
```

只读 metadata / recall，继续使用 Admin Token；不暴露完整 vector，不接受任意 Provider URL/API Key，也不注册 Fake Provider 供生产 API 调用。

## Migration

当前 head：

```text
20260808_0007
```

文件：

```text
migrations/versions/20260808_0007_m3b_signal_embeddings.py
```

新增：

```text
vector extension readiness
signal_embeddings
FK / UNIQUE / CHECK / ordinary indexes
```

没有 backfill、网络请求、Provider 调用、HNSW、IVFFlat 或 Event centroid。

## M3-B 明确禁止进入的范围

- Dedup decision；
- SimHash / MinHash；
- Event clustering；
- automatic event matching / creation；
- Event merge / split；
- Event centroid；
- 自动 `EventSignal attached_by=embedding`；
- LLM event boundary；
- M4 AI Gateway / Evidence / Editorial Scoring；
- Web Event Workbench。

## CI Gate

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

M3-B 业务实现已在 PostgreSQL 16 + pgvector 中通过 297 项 pytest；最终文档 HEAD 仍以 PR #12 最新 CI 为准。

## 开发原则

- 每个子阶段独立分支、独立 PR；
- 前一 PR 合并后才进入下一工程阶段；
- 下一阶段始终从最新 `main` 派生；
- PR 不自行合并；
- Engineering Complete 与 Real-world Validation Complete 分开表达；
- Deferred / NOT_TESTED 不得伪造 PASSED；
- Connector 不写 Event/Embedding；
- RawSignal 保留采集事实边界；
- M3 Processing 与采集层解耦；
- M3-B Recall 只返回候选，不做聚类结论。
