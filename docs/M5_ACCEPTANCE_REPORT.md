# M5 Acceptance Report

> 本文记录 M5 工程阶段状态。M5-A/M5-B 完成不代表 M5 Overall 完成，也不改变历史真实验证状态。

## 阶段状态

- **M5-A Editorial Workbench：COMPLETE / MERGED**
- **M5-B Daily Candidates / Editorial Workflow：COMPLETE / MERGED**
- **M5-C Publication / Performance Feedback：COMPLETE / PR #22 OPEN**
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

## M5-C 交付范围

M5-C 新增 Publication 与 Performance Feedback 的独立、append-only artifact：

- Workflow Publication 绑定 exact Draft，并要求当前 Editorial Decision 为 `adopt`；冻结 Candidate、Score、Risk、Draft provenance，不把 `adopt` 伪装为 Published；
- Manual Backfill 必须显式说明原因，仍不回写或改变 Candidate Rank、Event lifecycle、Trend、Score、Card、Pack、Draft 的既有真相；
- 手工观测与 CSV 导入都写入 append-only Performance snapshot；同一快照幂等，修正产生新快照而非覆盖历史；
- CSV preview 无业务写入，apply 使用文件内容 identity 幂等且记录 import run；空值、百分比、负数和时区输入均有显式校验；
- Web 提供 Publication 记录、Performance Feedback 与 Candidate 页面已发布计数展示；Actor 缺失时写操作保持 disabled。

## Migration

M5-C 新增 migration。

Alembic head 保持：

`20260810_0015_m5c_publication_performance`

已完成 `upgrade head → downgrade -1 → upgrade head → downgrade base → upgrade head` 往返，最终 revision 为 `20260810_0015`（迁移文件 `20260810_0015_m5c_publication_performance`）。

## 验收测试

M5-C 定向 PostgreSQL 测试覆盖 workflow provenance/adoption、manual backfill、merged Event boundary、Publication 并发 identity、Performance 空值/零值/修正、CSV preview/apply/idempotency、validation 与 bounded query。

新增 Web Mock API 测试覆盖 Event Explorer、Evidence 分级、Source URL、Unavailable Trend、Original/Effective Score、Human Override、Card/Pack、AI/Human Draft version、R3 approval、stale context、Merge/Split、Actor 缺失、安全 URL 与原 M1～M4 导航保留。

本地完整 pytest 为 `511 passed, 1 warning`；M3 concurrent regression、offline evaluation、performance baseline，ruff、mypy、Alembic 五步、Definition sync ×2 及 Web `lint`、`typecheck`、`test -- --run`、`build` 已通过。Windows symlink safety regression 使用 junction 覆盖同一根目录逃逸边界。AI 测试继续 offline only；exact-head CI 仍是最终验收。

## 下一阶段

M5-C PR #22 保持 Open，等待人工审查与 exact-head CI。**M5-D NOT STARTED**，M5 Overall 仍为 `NOT COMPLETE`。
