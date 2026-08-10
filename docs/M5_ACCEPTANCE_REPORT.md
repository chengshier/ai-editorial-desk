# M5 Acceptance Report

> 本文记录 M5 工程阶段状态。M5-A/M5-B 完成不代表 M5 Overall 完成，也不改变历史真实验证状态。

## 阶段状态

- **M5-A Editorial Workbench：COMPLETE / MERGED**
- **M5-B Daily Candidates / Editorial Workflow：COMPLETE / PR #21 OPEN**
- **M5-C Publication / Performance Feedback：NOT STARTED**
- **M5-D Hardening / Real E2E / MVP Closeout：NOT STARTED**
- **M5 Overall：NOT COMPLETE**

继续保留：

- **M4 Overall Engineering：COMPLETE**
- **Production AI Provider Validation：NOT_TESTED**
- **M2 Real Smoke Validation：DEFERRED / NOT_TESTED**
- **M2 Real-world Validation：NOT COMPLETE**

## M5-A 交付范围

M5-A 将 M1～M4 已有能力整合为日常编辑工作台，不重新实现 Event、Evidence、Trend、Editorial Score、Event Card、Editorial Pack 或 Draft 业务语义。

新增只读 Workbench Query API：

- `GET /api/v1/admin/workbench/overview`
- `GET /api/v1/admin/workbench/events`
- `GET /api/v1/admin/workbench/events/{event_id}`
- `GET /api/v1/admin/workbench/events/{event_id}/signals`

Web 工作台提供：

- Editorial Overview：Event 生命周期、近 24h 变化、Evidence / Unknown / Artifact、R3/R4 与现有 Collection/Risk Health 摘要；
- Event Explorer：分页、生命周期/分类/merged/risk/evidence/score/draft/时间/文本筛选，以及普通时间或 Effective Score 排序；
- Event Workbench：Overview、Evidence、Sources & Timeline、Trend & Score、Card & Pack、Drafts；
- Human Evidence、Unknown、Merge/Split、Trend calculate、Human score/override、Human Draft/Revision 继续复用既有业务 API；
- AI Score / Draft Preview 与 Apply 均只在用户显式点击后调用既有 AIGateway 路径；
- Markdown Export 继续使用 M4-D deterministic backend exporter。

## 查询与性能边界

`EditorialWorkbenchQueryService` 是只读 projection：不调用 AI、不写业务状态、不复制 Write API。Event list 先分页 Event，再用固定数量的批量查询装配 latest Trend、AI/Human Score、Override、Evidence/Unknown、Card/Pack/Draft 等摘要；不采用每 Event 分别请求多个 API 的 N+1 模式。

EventSignal 工作台投影仅返回可展示元数据与原始 URL，不返回 `raw_payload`。Workbench API 和 UI 都不得展示 credential、Authorization、API Key、Cookie、完整 Prompt 或 embedding vector。

## 语义与安全边界

- Event lifecycle (`emerging/growing/stable/declining/resolved`) 与未来 M5-B Editorial Decision 分离；
- Overview 不是 Candidate Pool，不生成 TOP10/TOP3，不持久化 DailyCandidate；
- Unknown 不显示为 Fact，`single_source` 不显示为 confirmed；
- Trend feature unavailable 明确显示 `Unavailable + reason`，不伪装成 0；
- Original AI Score 与 Effective Score 同时保留，Human Override 明确标记；
- merged Event 保留历史 Artifact 可读，新写操作禁用并显示 target Event；
- Actor 缺失时写操作提前 disabled；Admin Token / Actor 沿用 `sessionStorage`；
- 外部 Source URL 仅允许 `http/https`，使用 `target="_blank" rel="noopener noreferrer"`；
- R3/R4、stale context、citation validation、Human verification 等最终规则始终由原后端业务 Service/API 决定；
- 不自动调用 AI、不自动创建 Card/Pack/Draft、不自动发布、不自动 fallback 到 Fake Provider。

## M5-B 交付范围

M5-B 新增确定性 Daily Candidate snapshot、候选池读模型和人工 Editorial Decision history。Candidate Rank 是可解释的算法结果，Human Editorial Decision 独立记录 `adopt/watch/drop/archive/restore`；二者不互相伪装，也不改变 Event lifecycle。

Candidate Apply 对同一输入保持幂等，并使用 PostgreSQL 并发保护避免重复 run。M5-B 不自动调用 AI、不自动发布、不修改 M3/M4 frozen semantics；Web 只展示与调用既有安全边界内的管理能力。

## Migration

M5-B 新增 migration。

Alembic head 保持：

`20260810_0014_m5b_daily_candidates`

已在全新、独立的本地 PostgreSQL 测试库完成 `upgrade head → downgrade -1 → upgrade head → downgrade base → upgrade head` 往返，最终 revision 为 `20260810_0014`（迁移文件 `20260810_0014_m5b_daily_candidates`）。此前旧测试库的 downgrade 问题记录为 local stale test data，不作为 migration failure。

## 验收测试

M5-B 定向 PostgreSQL 测试覆盖 deterministic ranking、explainability、input idempotency、concurrent apply、decision risk/archive/restore/drop、stale protection、evidence merge、Admin safe projection、bounded query 与 Workbench read-only overlay。

新增 Web Mock API 测试覆盖 Event Explorer、Evidence 分级、Source URL、Unavailable Trend、Original/Effective Score、Human Override、Card/Pack、AI/Human Draft version、R3 approval、stale context、Merge/Split、Actor 缺失、安全 URL 与原 M1～M4 导航保留。

本地 M5-B 定向测试已通过；Web `lint`、`typecheck`、`test -- --run`、`build` 已通过。Windows 的 `test_browser_profile_resolver_rejects_missing_and_symlink` 受 `WinError 1314` symlink privilege 限制，未改变生产代码或测试语义；Linux exact-head GitHub Actions 仍是最终验收。AI 测试继续 offline only。

## 下一阶段

M5-B PR #21 保持 Open，等待人工审查与 exact-head CI。下一阶段为 **M5-C Publication / Performance Feedback**，当前 `NOT STARTED`；M5-D 也保持 `NOT STARTED`，M5 Overall 仍为 `NOT COMPLETE`。
