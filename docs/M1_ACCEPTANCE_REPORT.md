# M1 阶段验收报告

> 验收范围：M1-A、M1-B、M1-C、M1-D。  
> 验收日期：2026-08-07。  
> 本报告只确认 M1 范围，不声明 M2、M3 或后续 AI 能力已经完成。

## 1. 结论

M1 的工程开发范围与 CI 验收已经完成，可以在 PR #6 合并后进入 M2。

最终代码候选在 GitHub Actions 的 PostgreSQL 16 + pgvector 环境中通过：

- `ruff check .`；
- `mypy apps packages`，99 个 Python 源文件无类型错误；
- `pytest`：120 passed；
- Alembic：`upgrade head → downgrade -1 → upgrade head → downgrade base → upgrade head` 完整往返；
- Connector Definition 连续同步两次，第二次 `created=0 / updated=0 / unchanged=11 / failed=0`；
- Web `npm run lint`、`npm run typecheck`、`npm test -- --run`、`npm run build` 全部成功；
- Web 单元测试：6 个 test files、8 tests passed。

当前仅有非阻塞依赖/工具提示：FastAPI/Starlette TestClient 的 httpx 弃用提示、React Fast Refresh 的单文件多导出 warning，以及 GitHub Actions Node 20 兼容性弃用提示；均不影响本次验收结果。

## 2. M1 验收矩阵

| 验收项 | 实现位置 | 主要测试/CI | 状态 | 已知限制 |
| --- | --- | --- | --- | --- |
| FastAPI 可运行 | `apps/api/` | API、ready/health 与全量 pytest | 通过 | 当前 Admin Token 是内部 MVP，不是正式 RBAC |
| PostgreSQL + pgvector 可运行 | `docker-compose.yml`、`packages/database/` | GitHub Actions `pgvector/pgvector:pg16` | 通过 | CI 使用独立测试库 |
| Migration 完整可往返 | `migrations/versions/20260806_0001*` 至 `20260807_0004*` | `test_m1d_migration.py` + CI 五步 Alembic | 通过 | 不修改历史已合并 migration |
| Connector SDK 可扩展 | `packages/connectors/base.py`、Registry/Definition | Connector 测试、Definition 同步 | 通过 | MediaCrawler 七个平台仍未进入真实运行 |
| Definition Registry 存在 | `packages/connectors/definitions/` | Definition 双次同步 CI | 通过 | registered 不等于 implemented/validated |
| JSON Schema / UI Schema 存在 | Definition Manifest、M1-B Schema 服务 | Schema/API/Web 测试 | 通过 | 仅实现 M1 所需 Schema 子集 |
| Instance 无需改 YAML 即可管理 | Instance API + `apps/web/src/pages/InstancesPage.tsx` | `InstanceSourcePages.test.tsx` | 通过 | 内部管理工作台，不是正式权限系统 |
| Web 可新建、编辑、启停和测试 Connector | `apps/web/`、Instance/Source API | Web lint/typecheck/8 tests/build | 通过 | Test Run/Run Now 仍受 Runtime、Budget、Risk Guard 约束 |
| Scheduler 可持续触发 | `apps/scheduler/main.py`、`packages/scheduling/scheduler.py` | `test_scheduler_tick_runs_runtime_once_and_advances_schedule` | 通过 | MVP 为 asyncio + PostgreSQL 轮询，无 Redis/Celery |
| 调度状态持久化 | `collection_schedules`、`collection_schedule_triggers`、`scheduler_instances` | M1-D migration 与 scheduler 集成测试 | 通过 | 不依赖内存 Job 存储 |
| Scheduler lease 并发单赢家 | `packages/scheduling/repository.py` | `test_schedule_lease_has_one_winner_and_expired_lease_is_reclaimable` | 通过 | Lease 为数据库最终保证 |
| Lease 过期可恢复 | 同上 | 同上 | 通过 | 过期 RUNNING 时间槽不会自动盲目重跑，而是进入人工检查策略 |
| 同一 schedule 时间槽不重复触发 | `collection_schedule_triggers` 唯一约束 | `test_schedule_slot_is_unique_and_schedule_survives_new_session` | 通过 | 通过数据库唯一约束而非进程 mutex |
| Scheduler heartbeat 持久化 | `scheduler_instances` | `test_scheduler_heartbeat_is_persisted` | 通过 | 用于内部状态页，不是集群编排系统 |
| RawSignal 统一 | `packages/signals/`、`raw_signals` | M1-C/M1-D RawSignal 测试 | 通过 | Event/EventSignal 不属于 M1 |
| 重复任务不会重复入库 | RawSignal v1 幂等键 + PostgreSQL unique/ON CONFLICT | M1-C 并发测试、`test_hotlist_runtime_m1d.py` | 通过 | 不以“先查再插”为并发保护 |
| RSS 可生成信号 | `packages/connectors/rss/` | RSS/Atom fixture、Runtime 测试 | 通过 | CI 不访问真实互联网；真实 validated 需人工 smoke |
| Manual URL 可生成信号 | `packages/connectors/manual/` | Manual URL、安全 HTTP、Runtime 测试 | 通过 | 真实 validated 需人工 smoke；不支持登录态/浏览器绕过 |
| 至少一个国内热榜入口可生成信号 | `packages/connectors/hotlist/baidu.py` | `test_hotlist_connector_m1d.py`、`test_hotlist_runtime_m1d.py` | 通过 | 使用百度公开实时热榜；若来源限制访问则停用，不绕过 |
| Hotlist 网络安全限制 | `SafeHTTPFetcher` + Hotlist Connector | 私网 Redirect、Content-Type/响应限制等测试 | 通过 | CI 使用 fixture/mock，不依赖外网 |
| Checkpoint 可查看 | Checkpoint Admin API + Web Checkpoints 页面 | API/集成测试、Web build | 通过 | 默认只读；reset 是独立高风险操作 |
| Checkpoint reset 使用 expected_version | `CheckpointDebugService` | 并发 reset：一成功、一 VersionConflict | 通过 | 不提供任意修改 checkpoint 接口 |
| Checkpoint reset 有审计且不删除 RawSignal | AuditLog + reset 服务 | `test_checkpoint_reset_is_optimistic_audited_and_keeps_raw_signals` | 通过 | reset 只重置游标状态 |
| Run 日志与详情可查看 | Run Debug API + Runs 页面 | API/Web/集成测试 | 通过 | 错误与 metadata 经过安全边界，不返回凭据原值 |
| stale Run 可识别但不自动重新执行 | `RunRecoveryService` | stale/retry PostgreSQL 集成测试 | 通过 | 需要管理员判断后 mark failed/cancel/retry |
| Retry 创建新 Run，不覆盖旧 Run | `parent_run_id`、`retry_count`、Runtime | `test_stale_run_is_only_identified_then_retry_creates_new_run` | 通过 | 不存在无限自动 retry |
| Retry 重新经过 Budget / Risk Guard | `CollectorRuntime` | `test_retry_reenters_budget_and_risk_guard` | 通过 | 明确风险仍进入人工流程 |
| 明确风险不进入普通重试 | Risk Guard + Runtime | M1-C Risk 测试 + M1-D retry 测试 | 通过 | 不自动换号、代理轮换、验证码绕过 |
| 达到 Budget 后任务被阻止 | `collection_budgets`、数据库 usage/锁 | M1-C 预算并发 + M1-D retry Budget 测试 | 通过 | requested_limit 不能绕过 Budget |
| 单一 Connector 失败不影响其他 Connector | 每次 Run 独立短事务与 Runtime 编排 | Runtime 失败/部分成功测试 | 通过 | 不建立跨 Connector 大事务 |
| 配置错误不会覆盖上一有效配置 | M1-B Schema 校验 + config version/审计 | M1-B API/Schema 测试 | 通过 | 前端校验仅改善体验，后端 Schema 是最终权威 |
| 敏感凭据不从 API/Web 明文读取 | SanitizedJSONB、API Schema、Web 页面 | 安全/脱敏测试、`InstanceSourcePages.test.tsx` | 通过 | Web 不显示 Cookie、Token、credential_ref/browser_profile_ref 原值 |
| Connector Validation 状态存在 | `connector_validation_records`、Validation API | M1-D Validation 集成测试 | 通过 | Definition/CI Mock 不会自动设置 validated=true |
| PASSED 验真绑定人工成功 Run 证据 | `ConnectorValidationService._require_real_smoke_evidence` | Validation 测试 | 通过 | 服务端要求非 CI/Mock、`real_smoke_test`、成功 Test/Manual Run ID；实际外网 smoke 仍由管理员低量执行 |
| Web 基础工作台 | React + Vite + TypeScript `apps/web/` | lint、typecheck、6 files/8 tests、production build | 通过 | 仅 M1 内部连接器中心，不是最终编辑工作台 |

## 3. M1-D 新增数据结构

独立 migration：`20260807_0004_m1d_scheduler_workbench.py`。

新增：

- `collection_schedules`；
- `collection_schedule_triggers`；
- `scheduler_instances`；
- `connector_validation_records`。

同时为既有 Run/Checkpoint 增加 M1-D 调试与恢复所需字段。M1-A/B/C migration 不回改。

## 4. 真实低量 Smoke 与 validated 规则

CI 明确不连接真实外部网站，因此 **CI 通过不等于真实 validated=PASSED**。

M1 已提供内部管理操作：

1. 对 RSS / Hotlist 使用 Connector Test Run；
2. 对 Manual URL 使用 Manual Import/Test Run；
3. 单次使用很小的 `requested_limit`，仍经过 Budget、Risk Guard、SSRF、Checkpoint 和 RawSignal 幂等；
4. 只有真实低量运行得到 `SUCCEEDED` Run 后，管理员才可携带 Actor 和该 `run_id` 记录 PASSED；
5. Validation Service 拒绝 CI/Mock 环境 PASSED，拒绝未绑定成功 Test/Manual Run 的 PASSED；
6. implementation_version 改变后，旧验真结果按 EXPIRED 解释。

因此本报告不伪造当前数据库中 RSS、Manual、Hotlist 已存在真实 PASSED 记录；运营 `validated` 状态应由实际环境的人工 smoke 结果决定。

## 5. 国内热榜来源

M1-D 选择百度官方实时热榜作为首个国内低风险入口：

- 官方页面：`https://top.baidu.com/board?tab=realtime`；
- Connector 使用公开 JSON：`https://top.baidu.com/api/board?platform=wise&tab=realtime`；
- 不使用登录、Cookie、验证码、签名破解、浏览器指纹、代理轮换；
- 使用低频、小条数、明确 User-Agent、超时、响应大小与 Content-Type 限制；
- 复用 SafeHTTPFetcher 的 SSRF/Redirect 防护；
- CI 仅使用 fixture/mock；
- 如果后续来源出现明确访问限制或风控，立即停用并重新选择公开来源，不绕过限制。

## 6. M1 明确不包含

以下能力没有在 M1 中提前实现：

- Event / EventSignal；
- Embedding、pgvector 相似检索、去重与事件聚类；
- 人工合并/拆分事件；
- AI Gateway、AI Provider、AI 评分、证据提取、稿件生成；
- MediaCrawler 七个平台真实运行与五项增强；
- Redis、Celery、大规模 Worker 集群；
- 正式用户认证/RBAC。

Event、Embedding 和聚类仍按正式路线进入 M3；下一开发阶段仅进入 M2。

## 7. 最终判定

**M1-A：完成。**  
**M1-B：完成。**  
**M1-C：完成。**  
**M1-D：完成。**  
**M1 工程开发与 CI 验收：完成。**

PR #6 仍应保持 Open，等待最终代码审查和人工合并；合并后再新开开发窗口进入 M2。
