# M5 Acceptance Report

> 本文记录 M5 工程阶段状态。M5-A 完成不代表 M5 Overall 完成，也不改变历史真实验证状态。

## 阶段状态

- **M5-A Editorial Workbench：COMPLETE（PR Open，待人工合并）**
- **M5-B Daily Candidates / Editorial Workflow：NOT STARTED**
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

## Migration

M5-A **NO NEW MIGRATION**。

Alembic head 保持：

`20260809_0013_m4d_editorial_pack_drafts`

UI tab、筛选、排序、当前 Event 等状态均为前端状态，不写数据库。

## 验收测试

新增 PostgreSQL Workbench 聚合测试覆盖：分页/筛选、merged include/exclude、effective Human override、Evidence/Draft presence、latest artifact、detail aggregation、安全 EventSignal 投影与 bounded query 策略。

新增 Web Mock API 测试覆盖 Event Explorer、Evidence 分级、Source URL、Unavailable Trend、Original/Effective Score、Human Override、Card/Pack、AI/Human Draft version、R3 approval、stale context、Merge/Split、Actor 缺失、安全 URL 与原 M1～M4 导航保留。

最终工程验收以本 PR exact-head GitHub Actions 为准：`ruff`、`mypy`、全量 `pytest`、M3 regression/evaluation/performance、Alembic 五步往返、Definition sync ×2、Web lint/typecheck/test/build。AI 测试继续 offline only。

## 下一阶段

下一阶段为 **M5-B Daily Candidates / Editorial Workflow**，但只有 M5-A PR 经人工审查并合并后才能开始。本 PR 不实现 M5-B。
