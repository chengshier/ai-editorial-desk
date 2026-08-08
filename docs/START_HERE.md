# AI 编辑部项目开发入口

## 当前阶段

- **M1：COMPLETE / 已合并**；
- **M2 Engineering：COMPLETE / 已合并**；
- **M2 Real Smoke Validation：DEFERRED / NOT_TESTED**；
- **M2 Real-world Validation：NOT COMPLETE**；
- **M3-A Event / EventSignal：Engineering COMPLETE，PR #11 Open**；
- **M3-B Embedding：NOT STARTED**；
- **M3-C Dedup / Clustering：NOT STARTED**；
- **M3-D：NOT STARTED**。

当前 M3-A 分支：

```text
feature/m3a-event-foundation
```

当前 PR：

```text
#11 feat: 完成 M3-A Event与EventSignal基础
```

PR #11 保持 Open，不自行合并。只有 PR #11 合并后，才允许从**最新 `main`** 创建独立 M3-B 分支；不得从 `feature/m3a-event-foundation` 继续派生下一阶段。

M2 Real Smoke Deferred 状态继续保留：当前 B站 / 知乎 / 微博 Real Smoke 与 Validation 均不是 PASSED；进入 M3 Engineering 不等于 M2 Real-world Validation 已完成。

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
11. `../third_party/MEDIACRAWLER_UPSTREAM.md`
12. `../third_party/README.md`

冲突优先级：DECISIONS → 综合开发实施规划 → 技术开发文档 → PRD。阶段验收报告记录当前工程事实，但不得覆盖上述正式架构决策。

## 已完成工程基线

M1 已建立：

- Async SQLAlchemy / Alembic / PostgreSQL 16 + pgvector；
- Connector Definition / Instance / Platform Account；
- Source / RawSignal / Collection Budget；
- CollectionTask / CollectorRuntime；
- Run 原子领取、stale 检查、人工 retry/cancel；
- Checkpoint 乐观更新和安全 reset；
- Risk Guard / PlatformRiskEvent / Account 状态；
- RSS / Manual URL / 百度实时 Hotlist；
- PostgreSQL Scheduler / Lease / 时间槽去重；
- Connector Validation；
- React + Vite + TypeScript 连接器工作台。

M2 已建立：

- MediaCrawler Adapter / Runtime 集成；
- 七平台 Mapper、capabilities/config_schema/ui_schema；
- RawSignal / `raw_signal_comments` 标准化与 PostgreSQL 幂等持久化；
- Checkpoint / Incremental / Resume；
- Account / Browser Profile abstraction；
- SignatureProvider；
- Platform Risk Signal；
- offline Smoke Harness；
- B站 / 知乎 low-volume search compatibility；
- M2 Real Smoke 环境与登录 preflight。

MediaCrawler 继续固定在：

```text
third_party/MediaCrawler/
upstream commit: 071c8c0acaece3e82f2532cffb19faeddc9ec1c3
license: NON-COMMERCIAL LEARNING LICENSE 1.1
```

M2-D 只保留经过审计的 B站 / 知乎低量 search compatibility patch；不修改登录、Cookie、CDP、Signature、Risk Guard、proxy、stealth、CAPTCHA 或账号逻辑。

## M3-A 正式边界

M3 总体处理链：

```text
RawSignal
→ Event / EventSignal       M3-A COMPLETE
→ Embedding                 M3-B NOT STARTED
→ Dedup / Event Clustering  M3-C NOT STARTED
```

M3-A 只建立最前面的正式数据与处理基础。

### Event

当前字段：

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

M3-A 不存在 Trend Engine，因此只建立合法状态结构，人工创建默认 `emerging`，不实现自动状态转换。

`summary / category / primary_language` 可以为空，`entities / keywords` 默认空结构；M3-A 不通过假 AI 内容补齐这些字段。`title` 为人工输入，不伪装为 AI 摘要。

### EventSignal

当前字段：

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

但 **M3-A Admin 写入只允许 `human`**。`embedding` / `llm` 只是合法未来来源值，不代表本阶段已经执行 Embedding 或 LLM。

### 唯一性与并发

最终数据库约束：

```text
UNIQUE(event_id, signal_id)
```

不对 `signal_id` 单独加 UNIQUE；同一 RawSignal 可以关联多个 Event。

重复/并发 attach 使用：

```text
Event SELECT ... FOR UPDATE
+ PostgreSQL INSERT ... ON CONFLICT DO NOTHING
+ UNIQUE(event_id, signal_id)
```

Service 正常幂等，PostgreSQL UNIQUE 是最终并发保护，不依赖单纯的“先 select 再 insert”。

### 聚合计数

Event 聚合字段永远从 EventSignal → RawSignal 实际关系重算：

```text
source_count   = COUNT(DISTINCT RawSignal.source_id)
platform_count = COUNT(DISTINCT RawSignal.platform)
```

客户端不能提交或覆盖这两个计数。M3-A 没有额外增加 `signal_count`。

### 时间语义

```text
first_seen_at = MIN(COALESCE(RawSignal.published_at, RawSignal.collected_at))
```

- 优先使用可靠 `published_at`；
- 缺失时回退 `collected_at`；
- 空 Event 为 `NULL`；
- 不使用当前时间伪装历史事件首次出现时间；
- detach 后基于剩余关联重新计算。

`last_updated_at` 表示 Event 处理层最后一次**有效业务变更**时间：

- manual create：设置当前 UTC；
- 首次有效 attach：推进；
- 有效 detach：推进；
- repeated attach：不推进；
- no-op repeated detach：不推进。

### RawSignal 不可变边界

Event 层是 RawSignal 之上的派生层。attach / detach / Event 事务失败不得修改或删除 RawSignal 的：

```text
original_url
canonical_url
external_id
collected_at
raw_payload
platform
source_id
```

EventSignal 的 RawSignal FK 使用 `ON DELETE RESTRICT`；Event 删除时关联可以通过 Event FK `ON DELETE CASCADE` 清理，但 M3-A 不提供 Event hard-delete API。

## M3-A Admin API

继续复用现有 `/api/v1/admin`、Admin Token、`X-Actor-ID` 与 AuditLog：

```text
POST   /api/v1/admin/events
GET    /api/v1/admin/events
GET    /api/v1/admin/events/{event_id}
GET    /api/v1/admin/events/{event_id}/signals
POST   /api/v1/admin/events/{event_id}/signals
DELETE /api/v1/admin/events/{event_id}/signals/{signal_id}
```

- list API 支持分页；
- Event list 支持 status 过滤；
- create / attach / detach 要求 Actor；
- EventSignal 返回关联元数据，不返回 RawSignal `raw_payload`；
- attach / detach 复用既有通用审计表；
- 本阶段不开发 Event Workbench 前端页面。

## M3-A Migration

当前 migration head：

```text
20260808_0006
```

文件：

```text
migrations/versions/20260808_0006_m3a_event_foundation.py
```

新增：

```text
events
event_signals
```

包含 PostgreSQL FK / UNIQUE / CHECK / INDEX；没有 vector、HNSW、IVFFlat 或 Embedding 字段。

## M3-A 明确禁止进入的范围

当前 PR 不得新增或启用：

- OpenAI / 云 Embedding；
- Ollama / 本地模型；
- vector similarity；
- HNSW / IVFFlat；
- centroid embedding；
- embedding provider/model routing；
- SimHash / MinHash；
- cosine / semantic similarity；
- automatic event matching；
- automatic event creation；
- automatic clustering；
- merge / split；
- LLM event boundary；
- AI Editorial Scoring。

Connector / CollectorRuntime 热路径继续与 Event 解耦：采集成功后不要求同步创建 Event。

## CI Gate

Python / PostgreSQL：

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
```

Web：

```bash
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

M3-A 的关键数据库测试必须在 PostgreSQL 上完成，不使用 SQLite 替代 FK / UNIQUE / CHECK / 并发验证。

## Real Smoke 延后策略继续有效

正式状态继续是：

```text
M2 Engineering Complete
M2 Real Smoke Validation Deferred / NOT_TESTED
M2 Real-world Validation NOT COMPLETE
```

当前真实联调环境未就绪并不阻塞 M3 Engineering，但 fixture/mock/CI 绝不能把任何真实平台 Validation 自动标记为 PASSED。

在 M5 宣布真实世界 / Production Validation 完成之前，必须至少补一次受控真实端到端平台 Smoke；优先从 B站或知乎开始。

## 开发原则

- 一个子阶段一个独立分支、独立 PR；
- 前一个 PR 合并后才进入下一个工程阶段；
- 下一阶段从最新 `main` 派生，不从 feature 分支继续派生；
- Commit / PR 使用中文；
- PR 不自行合并；
- Engineering Complete 与 Real-world Validation Complete 分离表达；
- Deferred / NOT_TESTED 不得伪造 PASSED；
- Connector 不写 Event；
- RawSignal 保留采集事实边界；
- M3 的语义处理只通过 Processing 层推进；
- 风险错误不普通重试；
- 不自动换号、不代理轮换、不破解验证码、不伪造指纹、不绕过平台限制。
