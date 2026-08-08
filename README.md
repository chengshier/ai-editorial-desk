# AI Editorial Desk

AI 编辑部系统：面向短视频创作者的多来源信息发现、资料整理、编辑判断与内容生产辅助系统。

**当前状态：M1 COMPLETE；M2 Engineering COMPLETE；M2 Real Smoke Validation = DEFERRED / NOT_TESTED；M2 Real-world Validation = NOT COMPLETE；M3-A COMPLETE；M3-B Embedding / Vector Recall Engineering COMPLETE；M3-C / M3-D NOT STARTED。**

开发入口见 [`docs/START_HERE.md`](docs/START_HERE.md)，M3 验收见 [`docs/M3_ACCEPTANCE_REPORT.md`](docs/M3_ACCEPTANCE_REPORT.md)，架构决定见 [`docs/DECISIONS.md`](docs/DECISIONS.md)。M2 Engineering 完成不等于真实平台验真完成，当前没有任何真实平台 Validation 被 M3-B 改写为 PASSED。

## 当前数据流

```text
Connector Definition / Source / Schedule
→ CollectionTask / CollectorRuntime
→ Budget + Risk Guard + Run
→ RSS / Manual URL / Hotlist / MediaCrawler Adapter
→ Platform Mapper
→ RawSignal / RawSignalComment
→ Checkpoint / Incremental / Resume

RawSignal
→ Event / EventSignal                         M3-A COMPLETE
→ EmbeddingInput(signal-text-v1)             M3-B COMPLETE
→ EmbeddingProvider Contract
→ versioned signal_embeddings
→ pgvector exact cosine similarity recall
→ Dedup / Event Clustering                   M3-C NOT STARTED
```

采集层继续与 M3 Processing 层解耦：Connector / CollectorRuntime 不创建 Event、不生成 Embedding、不等待 Embedding Provider，也不判断两个 Signal 是否属于同一事件。

## M3-A Event / EventSignal

M3-A 已建立正式 `events` / `event_signals`：

- `UNIQUE(event_id, signal_id)`，不对 `signal_id` 单独唯一；
- `source_count = COUNT(DISTINCT RawSignal.source_id)`；
- `platform_count = COUNT(DISTINCT RawSignal.platform)`；
- `first_seen_at = MIN(COALESCE(RawSignal.published_at, RawSignal.collected_at))`；
- `last_updated_at` 只在有效业务变更时推进；
- M3-A Admin attach 只使用 `human`；`embedding` / `llm` 仅作为未来合法 attached_by 值；
- Event 层不会修改 RawSignal 采集事实。

## M3-B Embedding / Vector Recall

M3-B 将 Embedding 定义为 RawSignal 之上的**可重建、版本化、不可覆盖派生 artifact**。

### SignalEmbedding

独立表：

```text
signal_embeddings
```

字段：

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

核心约束：

```text
UNIQUE(signal_id, embedding_version)
dimensions > 0
vector_dims(embedding) = dimensions
vector_norm(embedding) > 0
input_hash = 64-character SHA-256 hex
```

RawSignal 不承载单版本 embedding 字段；模型、Provider、输入拼接或维度语义发生变化时必须产生新的 `embedding_version`，旧版本保留，不 silent overwrite。

### Input Schema

当前确定性输入版本：

```text
signal-text-v1
```

仅使用规范化后的：

```text
RawSignal.title
RawSignal.text
```

不会加入 metrics、raw_payload、Cookie、credential、connector config 或 URL。title/text 都为空或纯空白时返回 `NO_EMBEDDABLE_TEXT`，不会 embed 空字符串或用 URL 伪装正文。最终发送给 Provider 的规范化文本计算 SHA-256 保存为 `input_hash`。

### Provider Contract

`packages/embeddings/` 仅建立 Embedding 专用 `EmbeddingProvider` Protocol 和 request/result domain objects，表达：

- provider key；
- model name；
- embedding version；
- dimensions；
- batch inputs / vectors；
- optional usage / latency / error metadata。

M3-B 没有生产默认 Fake Provider，也没有 OpenAI / Anthropic / Gemini / Ollama Adapter，没有 Chat Completion、Prompt Registry 或通用 AI Gateway。

### Batch Processor

受控 Batch Processor：

- signal IDs 去重；
- batch size 可配置，不一次加载整表；
- Provider 调用位于数据库事务之外；
- 同 signal/version/input 直接 skip；
- 同 version 但 input/provider/model/dimension 语义变化返回 `EMBEDDING_VERSION_CONFLICT`；
- vector 数量错位、维度错误、NaN、Infinity、空向量、零向量拒绝落库；
- retry 显式有限，默认 1 次，最大 3 次；
- PostgreSQL `UNIQUE + ON CONFLICT DO NOTHING` 是并发最终保护。

### pgvector / Recall

Python 正式依赖 `pgvector`；migration `20260808_0007` 使用：

```sql
CREATE EXTENSION IF NOT EXISTS vector
```

downgrade 只删除 M3-B 表，不 `DROP EXTENSION vector`，因为 vector 是共享数据库能力。

向量列使用 dimensionless `VECTOR()`；每条记录另外保存 `dimensions`。Recall 必须同时过滤：

```text
same embedding_version
same dimensions
```

MVP 使用 PostgreSQL exact cosine search：

```text
similarity = 1 - cosine_distance
```

similarity 越大表示越相似。M3-B 只返回候选，不执行 Dedup/Clustering，不自动创建 Event，不自动写 `EventSignal attached_by=embedding`。

本批不建立 HNSW / IVFFlat。当前优先验证版本化、维度隔离和精确召回正确性；ANN 与参数调优后置到有数据规模依据的性能阶段。

## M3-B Admin API

只提供安全只读能力：

```text
GET  /api/v1/admin/embeddings/signals/{signal_id}
POST /api/v1/admin/embeddings/recall
```

metadata API 不返回完整 vector；Recall 返回 candidate signal ID、similarity、version、published/collected time、platform、source ID，不返回 RawSignal `raw_payload` 或完整向量。没有允许客户端提交任意 Provider URL/API Key 的生成接口。

## 主要结构

```text
apps/api/                              FastAPI 与内部管理 API
apps/scheduler/                        PostgreSQL Scheduler
apps/web/                              React 管理工作台
packages/connectors/                   Connector SDK / implementations
packages/collector_runtime/            Budget / Run / Risk / Runtime
packages/signals/                      RawSignal / comment 标准化与持久化
packages/events/                       M3-A Event / EventSignal
packages/embeddings/                   M3-B Input / Provider / Batch / Recall
packages/database/                     Async SQLAlchemy / PostgreSQL ORM
packages/risk_guard/                   风险保护
migrations/                            Alembic migrations
third_party/MediaCrawler/              pinned MediaCrawler
```

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

M3-B 业务实现已在 PostgreSQL 16 + pgvector CI 中通过 297 项 pytest；最终文档 HEAD 仍以 PR #12 的最新 CI 为准。

## 当前阶段边界

```text
M1 COMPLETE
M2 Engineering COMPLETE
M2 Real Smoke Validation DEFERRED / NOT_TESTED
M2 Real-world Validation NOT COMPLETE
M3-A Event / EventSignal COMPLETE
M3-B Embedding / Vector Recall COMPLETE
M3-C Dedup / Clustering NOT STARTED
M3-D NOT STARTED
M3 Overall NOT COMPLETE
```

M3-B PR 为 **#12 `feat: 完成 M3-B Embedding与向量召回基础`**，保持 Open，不自行合并。M3-C 只有在 PR #12 合并后才能从最新 `main` 创建独立分支，不得从 `feature/m3b-embedding-recall` 继续派生。
