# M3 验收报告

## 当前状态

```text
M3-A Event / EventSignal: COMPLETE
M3-B Embedding / Vector Recall: COMPLETE
M3-C Dedup / Clustering: NOT STARTED
M3-D: NOT STARTED
M3 Overall: NOT COMPLETE
```

M2 状态继续保持：

```text
M2 Engineering: COMPLETE
M2 Real Smoke Validation: DEFERRED / NOT_TESTED
M2 Real-world Validation: NOT COMPLETE
```

M3-B 工程完成不代表任何真实平台 Validation 已经 PASSED，也不代表 M3 整体完成。

## M3-B 开发基线

- PR #11 `feat: 完成 M3-A Event与EventSignal基础` 已合并；
- M3-B 基线 main：`1aa6d87350f8902fec6fffeb55cee3a7905385cc`；
- 分支：`feature/m3b-embedding-recall`；
- PR：#12 `feat: 完成 M3-B Embedding与向量召回基础`；
- PR #12 保持 Open，不自行合并；
- M3-B 分支从合并后的最新 main 直接创建，没有从 `feature/m3a-event-foundation` 派生。

## SignalEmbedding

Embedding 被定义为 RawSignal 之上的可重建、版本化派生 artifact，独立存储于：

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

artifact 不提供任意 update 语义；模型或输入规则升级不会覆盖旧版本。

### 唯一性与数据库约束

```text
UNIQUE(signal_id, embedding_version)
dimensions > 0
char_length(input_hash) = 64
provider_key / model_name / embedding_version / input_schema_version 非空
vector_dims(embedding) = dimensions
vector_norm(embedding) > 0
```

`signal_id` FK 指向 `raw_signals.id`，使用 `ON DELETE CASCADE`：RawSignal 删除时派生 Embedding 可以清理，但删除 Embedding 不会删除 RawSignal。

重复和并发写入使用 PostgreSQL `INSERT ... ON CONFLICT DO NOTHING` + UNIQUE 作为最终保护，不依赖单纯的 `SELECT → INSERT`。

## Vector Dimension 策略

M3-B 正式增加 Python `pgvector` integration，Embedding 列使用：

```text
dimensionless VECTOR()
```

不硬编码 1536、3072、768 等供应商维度。每条 artifact 单独保存 `dimensions`；真实 PostgreSQL 测试证明同一 Signal 的不同 embedding version 可以分别保存不同 dimensions。

Recall 只比较：

```text
same embedding_version
same dimensions
```

因此不同版本或不同维度不会互相计算距离。

## pgvector Extension

Migration：

```text
migrations/versions/20260808_0007_m3b_signal_embeddings.py
revision: 20260808_0007
down_revision: 20260808_0006
```

upgrade 使用：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Alembic 从 M3-B 起正式保证 vector schema capability 可用。downgrade 删除 `signal_embeddings`，但不 `DROP EXTENSION vector`，因为 extension 是共享数据库能力，未来其他表可能继续使用。

Migration 不 backfill 历史 RawSignal、不调用 Provider、不执行网络请求，也不填充假向量。

## Embedding Input

当前确定性输入版本：

```text
input_schema_version = signal-text-v1
```

只使用规范化后的：

```text
RawSignal.title
RawSignal.text
```

不会加入 metrics、raw_payload、Cookie、credential、connector config 或 URL。

规则：

- title + text：稳定拼接；
- title only / text only：分别生成有效输入；
- 空白统一规范化；
- title 与 text 均为空或纯空白：`NO_EMBEDDABLE_TEXT`；
- 不 embed 空字符串，不使用 URL 伪装正文；
- 最终实际发送给 Provider 的规范化文本计算 SHA-256，保存 `input_hash`。

## embedding_version 语义

`embedding_version` 是系统级稳定语义版本，不等于 `model_name`。

它必须覆盖：

- input schema；
- preprocessing 语义；
- provider / model 配置版本；
- dimensions 变化。

同一 `signal_id + embedding_version` 已存在且 input/provider/model/dimensions 语义一致时幂等 skip；如果 `input_hash` 或上述配置语义发生变化但 version 未升级，则返回：

```text
EMBEDDING_VERSION_CONFLICT
```

要求开发者升级 embedding version，不 silent overwrite。

## Embedding Provider Contract

`packages/embeddings/providers.py` 建立 M3-B 专用 `EmbeddingProvider` Protocol 与 request/result domain objects，表达：

```text
provider_key
model_name
embedding_version
dimensions
batch inputs
vectors
optional usage metadata
optional latency metadata
optional error metadata
```

Provider 不访问数据库；Repository 不调用 Provider；Service 协调二者。

当前没有生产 OpenAI / Anthropic / Gemini / Ollama Provider，也没有通用 AI Gateway。Fake / Mapping Provider 只存在 tests，不作为生产默认 Provider 注册。

## Batch Processor

`EmbeddingBatchProcessor` / `EmbeddingService` 支持：

- 显式 signal IDs；
- signal ID 去重；
- 可配置 batch size，不加载整张 RawSignal 表；
- Provider 调用位于数据库事务之外；
- 已有 artifact skip；
- 空文本 skip；
- wrong result count 整个 pending chunk 明确失败，不静默错位；
- dimension mismatch、空向量、NaN、Infinity、zero vector 拒绝写入；
- retryable provider/network failure 与 invalid response 分开；
- retry 默认 1 次，显式上限 3 次，不无限 retry；
- 返回 generated / skipped / failed counters 与逐项 code；
- 结构化日志记录 provider/model/version/dimensions/batch/counters/latency，不记录完整 vector、API Key 或完整正文。

RawSignal 在整个生成/失败流程中保持采集事实不可变。

## Exact Vector Recall

`SignalSimilarityService` / `SignalEmbeddingRepository.exact_cosine_recall` 提供 exact recall。

输入：

```text
signal_id
embedding_version
top_k
optional min_similarity
optional time_from
optional time_to
```

查询规则：

- same embedding_version；
- same dimensions；
- exclude self；
- optional threshold；
- optional effective time range，时间语义为 `COALESCE(published_at, collected_at)`；
- PostgreSQL exact cosine distance 排序。

统一相似度：

```text
similarity = 1 - cosine_distance
```

similarity 越大表示越相似。

输出：

```text
candidate_signal_id
similarity
embedding_version
published_at
collected_at
platform
source_id
```

不返回完整 vector 或 RawSignal `raw_payload`。

## Admin API

继续使用现有 Admin Token：

```text
GET  /api/v1/admin/embeddings/signals/{signal_id}
POST /api/v1/admin/embeddings/recall
```

metadata endpoint 只返回 provider/model/version/dimensions/input hash/created time；Recall 只返回安全候选元数据。

M3-B 没有提供允许客户端提交任意 Provider URL、API Key 或生产 Fake Provider 的生成 endpoint。

## ANN 决策

M3-B **没有**创建 HNSW / IVFFlat。

当前阶段优先保证：

- artifact versioning；
- dimension isolation；
- exact cosine correctness；
- PostgreSQL 并发幂等。

目前没有数据规模证据证明 exact search 不可接受，因此 ANN 与参数调优后置到有真实规模依据的性能阶段，避免提前增加运维和版本复杂度。

## PostgreSQL 测试

M3-B 新增并在真实 PostgreSQL 16 + pgvector 中覆盖：

- deterministic input builder、title+text/title only/text only/empty/whitespace/hash；
- dimensionless vector ORM/type；
- insert / metadata read；
- 同 Signal 不同 version、不同 dimensions 共存；
- duplicate idempotent；
- version conflict；
- PostgreSQL FK / UNIQUE / dimension CHECK / zero-vector CHECK；
- NaN / Infinity / empty / wrong dimensions 应用层拒绝；
- 两 Worker 同 signal/version 并发生成最终只有一条；
- RawSignal 不被 Embedding 操作修改；
- RawSignal 删除只向下 CASCADE embedding；
- batch 1 item / multi-item / mixed existing+missing+empty / wrong result count / retry boundary / batch size；
- exact cosine 排序、自身排除、top_k、threshold、time window；
- embedding version 隔离、dimension 隔离；
- missing target embedding；
- Admin unauthorized / metadata / recall / safe output；
- migration vector extension、dimensionless vector type、FK/UNIQUE/CHECK/INDEX 与 downgrade extension 保留；
- M1 / M2 / M3-A 全量回归继续执行。

## CI 验收

M3-B 业务实现 HEAD：

```text
1af81ad09181259c4128d23eaa5164274a7cc187
```

已完成一次完整 GitHub Actions PostgreSQL Gate：

- `ruff check .`：success；
- `mypy apps packages`：success，143 source files；
- PostgreSQL pytest：`297 passed / 1 warning`；
- Alembic：`upgrade head → downgrade -1 → upgrade head → downgrade base → upgrade head` 全部 success；
- Definition 第一次同步：`created=11 / updated=0 / unchanged=0 / failed=0`；
- Definition 第二次同步：`created=0 / updated=0 / unchanged=11 / failed=0`；
- Web：lint / typecheck / unit tests / production build 全部 success。

最终文档 HEAD 继续由 PR #12 最新 CI 复验。

## 阶段边界确认

M3-B 明确没有实现或调用：

- 真实 OpenAI / Anthropic / Gemini / Ollama Embedding；
- 通用 AI Gateway / Chat Completion / Prompt Registry；
- HNSW / IVFFlat；
- SimHash / MinHash；
- Dedup decision；
- Event clustering；
- automatic Event creation / merge / split；
- Event centroid；
- 自动写 `EventSignal attached_by=embedding`；
- LLM event boundary；
- M4 Evidence / Editorial Scoring；
- Web Event Workbench。

因此当前正式状态是：**M3-A COMPLETE；M3-B COMPLETE；M3-C / M3-D NOT STARTED；M3 Overall NOT COMPLETE**。
