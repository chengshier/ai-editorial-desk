# AI Editorial Desk

AI 编辑部系统：面向短视频创作者的多来源信息发现、资料整理、编辑判断与内容生产辅助系统。

**当前工程状态：M1 Engineering COMPLETE；M2 Engineering COMPLETE；M2 Real Smoke Validation = DEFERRED / NOT_TESTED；M2 Real-world Validation = NOT COMPLETE；M3 Overall Engineering COMPLETE；M4 Overall Engineering COMPLETE；M5-A Editorial Workbench Engineering COMPLETE / MERGED；M5-B Daily Candidates / Editorial Workflow COMPLETE / MERGED；M5-C Publication / Performance Feedback COMPLETE / PR #22 OPEN；M5-D NOT STARTED；M5 Overall = NOT COMPLETE。**

> Production AI Provider Validation 继续 `NOT_TESTED`。CI Fake/Mock/MockTransport 只验证工程契约，不能替代真实生产 Provider Validation；M2 真实平台验证状态也不会因为 M3/M4/M5-A 工程完成而自动升级。

开发入口见 [`docs/START_HERE.md`](docs/START_HERE.md)，M5-A 验收见 [`docs/M5_ACCEPTANCE_REPORT.md`](docs/M5_ACCEPTANCE_REPORT.md)，M4 验收见 [`docs/M4_ACCEPTANCE_REPORT.md`](docs/M4_ACCEPTANCE_REPORT.md)，架构决定见 [`docs/DECISIONS.md`](docs/DECISIONS.md)。

## 当前处理链

```text
Connector / CollectorRuntime
→ RawSignal / RawSignalComment
→ Event / EventSignal
→ Signal Embedding / Matching / Clustering
→ EvidenceClaim / EvidenceClaimSource / EventUnknown
→ Deterministic Trend Snapshot
→ AIGateway Editorial Scoring
→ Human Manual Score / Override
→ Effective Editorial Assessment
→ Event Card
→ Editorial Pack
→ Evidence-aware Draft / Human Revision
→ Deterministic Markdown Export
→ M5-A Editorial Workbench
→ M5-B Daily Candidates / Editorial Workflow
→ M5-C Publication / Performance Feedback
```

## M5-A Editorial Workbench

M5-A 是 M1～M4 后台能力的整合层，不重新实现 Event、Evidence、Trend、Score、Card、Pack 或 Draft 业务逻辑。

新增只读 Admin Query API：

```text
GET /api/v1/admin/workbench/overview
GET /api/v1/admin/workbench/events
GET /api/v1/admin/workbench/events/{event_id}
GET /api/v1/admin/workbench/events/{event_id}/signals
```

Web 继续使用现有 PageKey 架构，轻量分组为 Editorial / Collection / Configuration / AI。Event Workbench 包含：

```text
Overview
Evidence
Sources & Timeline
Trend & Score
Card & Pack
Drafts
```

Event Explorer 支持分页、lifecycle/category/merged/risk/evidence/score/draft/updated-time/text 筛选，以及 `last_updated_at`、`first_seen_at`、`traffic_total` 普通排序。这里的 score 排序不是 DailyCandidate ranking。

Workbench Query Service 只读数据库，不调用 AI，不复制业务 Write API。Merge/Split、Evidence verification、Unknown、Trend calculate、AI/manual Score、Human override、Card/Pack、AI Draft、Human Draft/Revision 等操作全部继续调用现有 M3/M4 Admin API。

关键边界：

- Event lifecycle 与未来 M5-B Editorial Decision 分离；
- Overview 不是 Candidate Pool，不生成 TOP10/TOP3，不持久化 DailyCandidate；
- Unknown 不是 Fact，`single_source` 不是 confirmed；
- unavailable feature 显示 `Unavailable + reason`，不伪装为数值 0；
- Original AI Score 与 Effective Score 同时可追溯，Human Override 明确显示；
- merged Event 历史 artifact 继续可读，新写操作禁用并显示 target Event；
- AI Score / Draft Preview / Apply 只能由用户显式触发；
- R3/R4 Risk Gate、stale context、citation 与 verification 仍由原后端 Service/API 最终校验；
- 不自动发布，不自动 fallback 到 Fake Provider。

## Evidence / Draft 安全语义

Draft 中的事实只能沿目标 Event 内真实 Evidence Claim citation chain：

- confirmed：可 `fact` 或 attributed；
- investigating：必须 attributed；
- single_source：必须 attributed；
- disputed：必须保留 disputed 语义；
- false：只能用于 debunk/fact-check；
- Unknown：只能作为 open question。

Human Draft / Human Revision 使用 append-only version chain，AI 原始版本不会被覆盖。Draft Apply 在 Provider 返回后重新校验 Evidence、Effective Editorial Assessment 与 Event merge 状态；R3/R4 继续受 Risk Gate 约束。

Markdown Export 是 deterministic backend renderer，不再次调用 AI。

## Admin Token / Sensitive Data

所有写操作继续要求 Admin Token + `X-Actor-ID`。Web 继续只使用 `sessionStorage` 保存当前会话 Token/Actor，不迁移到长期 `localStorage`。

Workbench API/UI 不展示 RawSignal `raw_payload`、credential、Authorization、API Key、Cookie、完整 Prompt 或 embedding vector。Source URL 仅允许 `http/https` 安全外链。

## AIGateway 边界

Editorial Scoring 与 AI Draft 继续使用既有 `AIGateway.generate_structured(...)`，完整经过 Route / Budget / Retry / Fallback / Schema / Invocation / Attempt / Usage / Cost。Provider 调用位于数据库长事务之外。Preview 仍可能产生 Invocation/token/cost，但不会写对应正式业务 artifact。

## M5-B Daily Candidates / Editorial Workflow

M5-B 在 M5-A 的只读工作台上增加了确定性的 Daily Candidate snapshot、候选池查询和人工 Editorial Decision history。候选排名与人工 `adopt/watch/drop/archive/restore` 决定分离保存；Apply 具备输入幂等与并发安全，不能自动调用 AI、自动发布或改变 M3/M4 既有语义。

## M5-C Publication / Performance Feedback

M5-C 增加 append-only `PublicationRecord`、手动 Performance snapshot 与 CSV import run。Workflow Publication 必须绑定 exact Draft，并要求当前 Human Editorial Decision 为 `adopt`；Publication/Performance 不回写 Candidate Rank、Event lifecycle、Trend 或 Editorial Score。历史补录必须显式标记 `manual_backfill`；Performance correction 追加新快照，不覆盖已有观测。

## 数据库迁移

M5-C 新增 migration。当前 migration head：

`20260810_0015_m5c_publication_performance`

0015 增加 Publication、Performance Import 与 Performance Snapshot；不修改 M1～M5-B 既有 artifact 语义。

## 基础验收

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

Definition 第二次同步必须 `created=0 / updated=0 / failed=0`；M3 concurrent regression、offline engineering evaluation、performance baseline 继续保留；所有 CI AI 测试保持离线。

## 下一阶段边界

M5-A、M5-B 已合并。M5-C 在 PR #22 保持 Open 等待人工审查；**M5-D NOT STARTED**；M5 Overall 仍未完成。
