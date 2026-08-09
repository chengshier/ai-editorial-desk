# AI 编辑部项目开发入口

## 当前阶段

```text
M1 Engineering COMPLETE / 已合并
M2 Engineering COMPLETE / 已合并
M2 Real Smoke Validation DEFERRED / NOT_TESTED
M2 Real-world Validation NOT COMPLETE
M3 Overall Engineering COMPLETE / 已合并
M4-A AI Gateway COMPLETE / 已合并
M4-B Evidence / Claim COMPLETE / 已合并
M4-C Trend / Editorial Score COMPLETE / 已合并
M4-D Event Card / Draft COMPLETE / 已合并
M4 Overall Engineering COMPLETE
Production AI Provider Validation NOT_TESTED
M5-A Editorial Workbench Engineering COMPLETE / PR #20 OPEN
M5-B Daily Candidates / Editorial Workflow NOT STARTED
M5-C Publication / Performance Feedback NOT STARTED
M5-D Hardening / Real E2E / MVP Closeout NOT STARTED
M5 Overall NOT COMPLETE
```

M5-A 在 `feature/m5a-editorial-workbench` 完成工程实现并通过 PR #20 提交人工审查。PR 必须保持 Open，只有人工合并后才能开始 M5-B。M5-A 工程完成不改变 Production AI Provider 与 M2 真实验证状态。

详细阶段验收见：

- `docs/M5_ACCEPTANCE_REPORT.md`
- `docs/M4_ACCEPTANCE_REPORT.md`
- `docs/M3_ACCEPTANCE_REPORT.md`

## 开发前必读

1. `docs/AI编辑部_综合开发实施规划_V1.2.md`
2. `docs/AI编辑部_技术开发文档_V1.2.md`
3. `docs/AI编辑部_PRD_V1.2.md`
4. `docs/DECISIONS.md`
5. `docs/M5_ACCEPTANCE_REPORT.md`
6. `docs/M4_ACCEPTANCE_REPORT.md`
7. `docs/M3_ACCEPTANCE_REPORT.md`
8. `docs/CHANGELOG.md`

## 当前完整处理链

```text
Connector Definition / Source / Schedule
→ CollectionTask / CollectorRuntime
→ RawSignal / RawSignalComment
→ Event / EventSignal
→ Signal Embedding / Matching / Clustering
→ EvidenceClaim / EvidenceClaimSource / EventUnknown
→ EventTrendSnapshot
→ Effective Editorial Assessment
→ Event Card
→ Editorial Pack
→ Draft / Revision
→ Markdown Export
→ M5-A Editorial Workbench
```

## M5-A Workbench 能力

Web 继续沿用现有 PageKey 架构，不引入 React Router 或大型 UI Framework。导航按逻辑整理为：

```text
Editorial
- Overview
- Events

Collection
- Sources
- Schedules
- Runs
- Checkpoints
- Accounts / Risk

Configuration
- Definitions
- Instances

AI
- AI Providers
- AI Routes
- AI Budgets
- AI Invocations
```

M5-A 新增只读查询：

```text
GET /api/v1/admin/workbench/overview
GET /api/v1/admin/workbench/events
GET /api/v1/admin/workbench/events/{event_id}
GET /api/v1/admin/workbench/events/{event_id}/signals
```

所有 Merge/Split、Evidence verification、Unknown、Trend calculate、Score、Card/Pack、Draft/Revision 等写操作继续调用 M3/M4 既有 Admin API，Workbench 不复制业务 Write API。

Event Workbench 分区：

```text
Overview
Evidence
Sources & Timeline
Trend & Score
Card & Pack
Drafts
```

关键冻结边界：

- Event lifecycle 与未来 M5-B Editorial Decision 分离；
- Overview 不是 DailyCandidate Pool，不生成 TOP10/TOP3，不保存 candidate rank；
- Unknown 不是 Fact，single_source 不是 confirmed；
- unavailable 必须显示 `Unavailable + reason`，不能显示假 0；
- Original AI Score 与 Effective Score 同时可追溯，Human Override 明确标记；
- merged Event 历史 Artifact 可读，但新写操作禁用并显示 target Event；
- Workbench Query Service 只读且绝不调用 AI；
- AI Score / Draft Preview / Apply 必须人工显式触发；
- R3/R4、stale context、citation、verification 最终规则仍由原业务 Service/API 决定；
- 不自动 fallback 到 Fake Provider；
- Admin Token / Actor 继续只保存在 `sessionStorage`；
- Source URL 仅允许安全 `http/https` 外链；
- 页面/API 不展示 raw_payload、credential、Authorization、API Key、Cookie、完整 Prompt 或 embedding vector。

## Production AI Provider Validation

```text
Production AI Provider Validation = NOT_TESTED
```

M4/M5-A 工程完成、Mock/Fake CI 成功都不能把该状态改成 PASSED。只有后续使用真实 production credential 完成人工真实网络验证后才可单独更新。

## Migration

M5-A **NO NEW MIGRATION**。当前 Alembic head 保持：

```text
20260809_0013_m4d_editorial_pack_drafts
```

UI tab、筛选、排序、当前 Event 等状态属于前端状态，不持久化到数据库。

## 完整验收命令

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

Definition 第二次同步必须 `created=0 / updated=0 / failed=0`。M3 concurrent regression、offline engineering evaluation、performance baseline 继续作为全量 CI Gate；所有 AI 测试 offline only。

## 下一阶段

下一阶段是 **M5-B Daily Candidates / Editorial Workflow**，当前 `NOT STARTED`。

开始 M5-B 必须：

1. 等待 PR #20 人工审查并合并；
2. 重新确认当时最新 `main`；
3. 从最新 `main` 创建独立 M5-B 分支；
4. 不从 `feature/m5a-editorial-workbench` 或旧 feature 分支继续派生；
5. 单独确认 M5-B 的 DailyCandidate / editorial decision 数据语义与 migration gate。
