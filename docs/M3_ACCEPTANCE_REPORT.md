# M3 验收报告

## 当前状态

```text
M3-A Event / EventSignal: COMPLETE
M3-B Embedding: NOT STARTED
M3-C Dedup / Clustering: NOT STARTED
M3-D: NOT STARTED
M3 Overall: NOT COMPLETE
```

M3-A 只完成 `RawSignal → Event / EventSignal` 正式数据与处理基础。本报告不将 M3-A 的完成表述为 M3 整体完成。

M2 状态继续保持：

```text
M2 Engineering: COMPLETE
M2 Real Smoke Validation: DEFERRED / NOT_TESTED
M2 Real-world Validation: NOT COMPLETE
```

进入 M3 Engineering 不代表任何真实平台 Validation 已经 PASSED。

## 开发基线

- PR #10 `feat: 完成 M2-D 离线验证准备与工程收口` 已合并；
- M3-A 基线 main：`f36d8f26dd0b282c2465bf09bd9fdadc0081d2ae`；
- 分支：`feature/m3a-event-foundation`；
- PR：#11 `feat: 完成 M3-A Event与EventSignal基础`；
- PR #11 保持 Open，不自行合并；
- M3-A 分支从最新 main 直接创建，没有从 M2 feature 分支派生。

## Event

正式字段：

```text
id
title
summary
category
status
first_seen_at
last_updated_at
primary_language
entities
keywords
source_count
platform_count
created_at
updated_at
```

状态合法值：

```text
emerging
growing
stable
declining
resolved
```

M3-A 没有 Trend Engine，因此只建立合法状态结构，人工创建默认 `emerging`，不实现自动状态转换。

`summary / category / primary_language` 允许为空，`entities / keywords` 默认空结构。M3-A 不调用 AI 补齐这些字段；`title` 由人工输入，不伪装为 AI 事件摘要。

## EventSignal

正式字段：

```text
id
event_id
signal_id
relation
confidence
attached_by
created_at
updated_at
```

relation：

```text
origin
report
repost
reaction
official_response
correction
```

attached_by 数据结构：

```text
rule
embedding
llm
human
```

数据库枚举为后续阶段保留完整合法值，但 M3-A Admin 写入只允许当前真实存在的 `human` attach；本阶段没有执行 rule auto-attach、Embedding 或 LLM。

`confidence` 在 Service 和 API 层拒绝 NaN / Infinity，并在 PostgreSQL 通过 CHECK 保证 `0 <= confidence <= 1`。

## 唯一性与并发幂等

最终关系唯一约束：

```text
UNIQUE(event_id, signal_id)
```

没有对 `signal_id` 单独增加 UNIQUE，因此同一 RawSignal 可以关联多个 Event。

attach 使用三层语义：

```text
Event SELECT ... FOR UPDATE
+ PostgreSQL INSERT ... ON CONFLICT DO NOTHING
+ UNIQUE(event_id, signal_id)
```

Service 对重复 attach 返回既有关联，不生成第二条记录；并发 attach 最终由 PostgreSQL UNIQUE 提供最终保护，不依赖“先 select 再 insert”。重复 attach 不覆盖既有 relation/confidence，也不推进 Event 的业务更新时间。

## 聚合计数

Event 聚合值只从 `EventSignal → RawSignal` 实际关系重算：

```text
source_count   = COUNT(DISTINCT RawSignal.source_id)
platform_count = COUNT(DISTINCT RawSignal.platform)
```

多个 Signal 属于同一个 Source 时，`source_count` 只计一次；多个 Source 属于同一 Platform 时，`platform_count` 只计一次。attach / detach 后重新计算；客户端不能提交或覆盖聚合计数。M3-A 未额外增加 `signal_count`。

## 时间语义

```text
first_seen_at = MIN(COALESCE(RawSignal.published_at, RawSignal.collected_at))
```

- 优先采用 RawSignal 的可靠 `published_at`；
- `published_at` 缺失时回退 `collected_at`；
- 空 Event 的 `first_seen_at = NULL`；
- detach 后根据剩余关系重新计算；
- 不使用当前时间伪装历史事件首次出现时间。

`last_updated_at` 表示 Event 处理层最后一次有效业务变更时间，全部为 UTC aware：

- manual create：设置当前 UTC；
- 首次有效 attach：推进；
- 有效 detach：推进；
- repeated attach：不推进；
- no-op repeated detach：不推进。

## RawSignal 安全边界

Event 是 RawSignal 之上的派生层。Event attach / detach / 失败事务不修改或删除 RawSignal 的：

```text
original_url
canonical_url
external_id
collected_at
raw_payload
platform
source_id
```

EventSignal 的 `signal_id` FK 使用 `ON DELETE RESTRICT`；`event_id` FK 使用 `ON DELETE CASCADE`。M3-A 不提供 Event hard-delete API。EventSignal detach 只删除关联本身，RawSignal 永久保留。

## Repository / Service

新增：

```text
packages/events/repositories.py
packages/events/services.py
```

职责：

- `EventRepository`：Event CRUD / list / `FOR UPDATE`；
- `EventSignalRepository`：关联查询、分页、PostgreSQL 幂等 attach、聚合统计、detach；
- `EventService`：业务事务、输入保护、attach/detach、聚合与时间更新、既有 AuditLog 复用。

继续复用项目唯一 AsyncSession 生命周期，没有建立第二套 Session/Engine。

Connector 和 CollectorRuntime 未接入 Event；采集成功后不要求同步创建 Event。

## Admin API

继续遵循现有 `/api/v1/admin`、Admin Token 和 `X-Actor-ID` 规则：

```text
POST   /api/v1/admin/events
GET    /api/v1/admin/events
GET    /api/v1/admin/events/{event_id}
GET    /api/v1/admin/events/{event_id}/signals
POST   /api/v1/admin/events/{event_id}/signals
DELETE /api/v1/admin/events/{event_id}/signals/{signal_id}
```

- Event list 支持分页与 status 过滤；
- EventSignal list 支持分页；
- create / attach / detach 要求 Actor；
- attach / detach 复用现有通用 AuditLog；
- EventSignal API 只返回关联元数据，不返回 RawSignal `raw_payload`；
- 本阶段没有开发 Event Workbench 前端页面。

## Migration

新增：

```text
migrations/versions/20260808_0006_m3a_event_foundation.py
```

Revision：

```text
20260808_0006
```

Down revision：

```text
20260807_0005
```

新增表：

```text
events
event_signals
```

包含 PostgreSQL FK / UNIQUE / CHECK / INDEX。M3-A migration 不包含 vector、HNSW、IVFFlat、centroid、Embedding model/provider/version 字段。

## PostgreSQL 测试

M3-A 新增测试覆盖：

- Event create / read / list / status / UTC / nullable future enrichment fields；
- EventSignal attach、重复幂等、并发重复、missing Event、missing RawSignal；
- confidence 越界、NaN、Infinity、relation / attached_by API 校验；
- 多 Signal 同 Source、多 Source 同 Platform、多 Platform、detach 重算、空 Event；
- `published_at` 优先、`collected_at` fallback、`first_seen_at` / `last_updated_at`；
- 同一 RawSignal 可属于多个 Event；
- attach 不修改 RawSignal、detach 不删除 RawSignal、失败操作不污染 RawSignal；
- EventSignal API 不回传 `raw_payload`；
- PostgreSQL schema introspection 验证 FK / UNIQUE / CHECK / INDEX，并显式验证不存在 `UNIQUE(signal_id)`；
- M1 / M2 全量回归继续执行。

## CI 验收

M3-A 业务实现 HEAD：

```text
c9db09bce9c7c41229594bb7d346b47899dc8291
```

GitHub Actions：

```text
CI #183
run id: 31247490678
status: completed / success
```

结果：

- `ruff check .`：success；
- `mypy apps packages`：success，134 source files；
- PostgreSQL pytest：`263 passed / 1 warning`；
- Alembic：`upgrade head → downgrade -1 → upgrade head → downgrade base → upgrade head` 全部 success；
- Definition 第一次同步：`created=11 / updated=0 / unchanged=0 / failed=0`；
- Definition 第二次同步：`created=0 / updated=0 / unchanged=11 / failed=0`，幂等；
- Web：lint / typecheck / unit tests / production build 全部 success。

## 阶段边界确认

本批明确没有实现或调用：

- OpenAI；
- 云 Embedding；
- Ollama / 本地模型；
- vector similarity；
- HNSW / IVFFlat；
- centroid embedding；
- SimHash / MinHash；
- cosine / semantic similarity；
- automatic event matching / automatic event creation；
- Dedup / Event Clustering；
- merge / split；
- LLM event boundary；
- AI Editorial Scoring。

因此当前正式状态是 **M3-A COMPLETE；M3-B / M3-C / M3-D NOT STARTED；M3 Overall NOT COMPLETE**。