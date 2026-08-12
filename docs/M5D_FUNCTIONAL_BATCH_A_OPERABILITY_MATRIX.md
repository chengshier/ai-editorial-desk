# M5-D Functional Batch A Operability Matrix

> 审计日期：2026-08-12。范围仅覆盖 Functional Batch A：Connector Instances、Sources、Schedules、Runs、Accounts / Risk、Event Explorer、Event Workbench。
>
> 本地后端 `/health` 与 `/ready` 均返回 200；带本地 Admin Token 的只读真实 smoke 已确认有 1 个实例、1 个信源、6 条运行记录、1 个账号、1 个 Event。为遵守 Human Actor、Risk Gate 与“不得自动采集”的约束，本审计没有自动执行任何写入、运行、归档、人工决定或 AI 操作。

## 分类说明

- **WORKING_VERIFIED**：已通过真实服务端请求验证，且无写入语义。
- **WIRED_UNVERIFIED**：前端 API、方法、路径与后端路由一致；真实写入需由显式人工 Actor 执行。
- **BLOCKED_BY_PREREQUISITE**：缺少 Actor、实体或人工确认时不能执行。
- **FRONTEND_BROKEN**：调用虽存在，但页面没有完整失败/进行中/结果闭环。
- **UI_ONLY / PLACEHOLDER**：页面不存在真正业务调用。
- **BACKEND_CAPABILITY_MISSING**：前端所需能力没有后端端点。
- **READ_ONLY_BY_DESIGN**：只读审计或历史信息。

## Connector Instances

| 用户操作 | Handler / API | 前置条件 | 预期副作用 | 当前状态 | 分类 | 修复 |
| --- | --- | --- | --- | --- | --- | --- |
| 刷新实例、定义、信源 | `GET /connector-instances`、`/connector-definitions`、`/sources` | Admin Token | 读取最新状态 | 三个真实 GET 均成功 | WORKING_VERIFIED | 否 |
| 新建实例 | `POST /connector-instances` | Actor、定义、名称、Schema 配置 | 新建实例并刷新列表 | 已有保存态、成功反馈和服务端刷新；未人工写入 | WIRED_UNVERIFIED | 已补 |
| 编辑 / 保存 | `PATCH /connector-instances/{id}` | Actor、合法配置 | 更新实例并刷新 | 已有保存态、成功反馈和服务端刷新；未人工写入 | WIRED_UNVERIFIED | 已补 |
| 启用 / 停用 | `POST /connector-instances/{id}/enable|disable` | Actor | 状态变更并刷新 | 已有处理态、成功反馈和服务端刷新；未人工写入 | WIRED_UNVERIFIED | 已补 |
| 归档 | `POST /connector-instances/{id}/archive` | Actor、显式确认 | 归档并刷新 | 已增加前端确认、归档态、错误反馈和刷新；未人工写入 | WIRED_UNVERIFIED | 已补 |
| 测试运行 | `POST /connector-instances/{id}/test-runs`，`dry_run=true` | Actor、已启用信源 | 创建 dry-run Run | 已展示 Run ID / 状态并提供运行记录入口；未以审计身份写入 | WIRED_UNVERIFIED | 已补回归测试 |
| 立即执行 | 同上，`dry_run=false` | Actor、已启用信源、人工动作 | 创建真实 Run | 已展示 Run ID / 状态并提供运行记录入口；未以审计身份写入 | WIRED_UNVERIFIED | 已补回归测试 |

## Sources

| 用户操作 | Handler / API | 前置条件 | 预期副作用 | 当前状态 | 分类 | 修复 |
| --- | --- | --- | --- | --- | --- | --- |
| 刷新列表与实例 | `GET /sources`、`/connector-instances` | Admin Token | 读取最新状态 | 真实 GET 成功 | WORKING_VERIFIED | 否 |
| 新建信源 | `POST /sources` | Actor、实例、必填字段 | 新建并刷新列表 | 已有保存态、成功反馈和服务端刷新；未人工写入 | WIRED_UNVERIFIED | 已补 |
| 编辑 / 保存 | `PATCH /sources/{id}` | Actor | 更新并刷新 | 已有保存态、成功反馈和服务端刷新；未人工写入 | WIRED_UNVERIFIED | 已补 |
| 启用 / 停用 | `PATCH /sources/{id}` | Actor | 更新 `enabled` 并刷新 | 已有处理态、成功反馈和服务端刷新；未人工写入 | WIRED_UNVERIFIED | 已补 |
| 归档 | `POST /sources/{id}/archive` | Actor、确认 | 归档并刷新 | 已增加前端确认、归档态、错误反馈和刷新；未人工写入 | WIRED_UNVERIFIED | 已补 |
| 测试运行 | `POST /connector-instances/{id}/test-runs`，`dry_run=true` | Actor、关联实例 | 创建 dry-run Run | 已展示 Run ID / 状态并提供运行记录入口；未以审计身份写入 | WIRED_UNVERIFIED | 已补回归测试 |

## Schedules

| 用户操作 | Handler / API | 前置条件 | 预期副作用 | 当前状态 | 分类 | 修复 |
| --- | --- | --- | --- | --- | --- | --- |
| 刷新 | `GET /schedules`、`/sources` | Admin Token | 读取最新状态 | 真实 GET 成功（当前 0 条） | WORKING_VERIFIED | 否 |
| 创建 | `POST /schedules` | Actor、Source、策略字段 | 持久化任务并刷新 | 已有保存态、成功反馈和服务端刷新；未人工写入 | WIRED_UNVERIFIED | 已补 |
| 暂停 / 恢复 | `POST /schedules/{id}/pause|resume` | Actor；暂停需 reason | 状态持久化并刷新 | 已有 pending、失败反馈与刷新；未以审计身份写入 | WIRED_UNVERIFIED | 已补回归测试 |
| 立即运行 | `POST /schedules/{id}/run-now` | Actor、人工启动 | 创建真实 Run | 已有 pending、失败反馈与刷新；未以审计身份写入 | WIRED_UNVERIFIED | 后续可补 Run 记录快捷入口 |
| 编辑任务 | 后端 `PATCH /schedules/{id}` 存在 | Actor | 更新任务 | 页面无编辑入口 | UI_ONLY / PLACEHOLDER | Batch A 不新增未设计 UI；记录能力 |

## Runs

| 用户操作 | Handler / API | 前置条件 | 预期副作用 | 当前状态 | 分类 | 修复 |
| --- | --- | --- | --- | --- | --- | --- |
| 筛选 / 刷新 | `GET /connector-runs?status=` | Admin Token | 重取运行记录 | 真实 GET 成功（6 条） | WORKING_VERIFIED | 否 |
| 打开详情 | `GET /connector-runs/{id}` | 已有 Run | 查看服务端详情 | 有真实 Run 可供只读 smoke | WORKING_VERIFIED | 否 |
| 人工重试 | `POST /connector-runs/{id}/retry` | Actor、失败/部分/取消 Run | 创建 retry Run | 已防止重复提交、显示失败反馈并刷新详情；未以审计身份写入 | WIRED_UNVERIFIED | 已补回归测试 |
| 取消运行 | `POST /connector-runs/{id}/cancel` | Actor、pending/running Run、reason | 持久化取消 | 已防止重复提交、显示失败反馈并刷新详情；未以审计身份写入 | WIRED_UNVERIFIED | 同上 |

## Accounts / Risk

| 用户操作 | Handler / API | 前置条件 | 预期副作用 | 当前状态 | 分类 | 修复 |
| --- | --- | --- | --- | --- | --- | --- |
| 刷新账号与风险 | `GET /platform-accounts`、`/platform-risk-events` | Admin Token | 读取状态 | 账号真实 GET 成功；当前无风险事件 | WORKING_VERIFIED | 否 |
| 进入人工复核 / 恢复 | `POST /platform-accounts/{id}/status` | Actor、状态机合法迁移 | 账号状态持久化并刷新 | 路由与 payload 一致，未人工写入 | WIRED_UNVERIFIED | 补 loading/成功反馈 |
| 解决风险事件 | 后端 `POST /platform-risk-events/{id}/resolve` | Actor、resolution_note | 风险事件已解决 | 已接入处理说明、提交状态与已解决展示；未以审计身份写入 | WIRED_UNVERIFIED | 已补回归测试 |

## Event Explorer

| 用户操作 | Handler / API | 前置条件 | 预期副作用 | 当前状态 | 分类 | 修复 |
| --- | --- | --- | --- | --- | --- | --- |
| 刷新 / 主筛选 / 更多筛选 / 排序 / 分页 | `GET /workbench/events` query | Admin Token | 服务端重新过滤与分页 | 真实 GET 成功（1 个 Event）；query 构造覆盖字段 | WORKING_VERIFIED | 否 |
| 打开事件工作台 | `onOpenEvent(id)` → PageKey/event context | 有 Event | 切换到 Workbench | 有前端行为测试；真实 Event 可读取 | WORKING_VERIFIED | 否 |

## Event Workbench

| 用户操作 | Handler / API | 前置条件 | 预期副作用 | 当前状态 | 分类 | 修复 |
| --- | --- | --- | --- | --- | --- | --- |
| 加载事件 / 切换 Tabs / 刷新 | `GET /workbench/events/{id}`、各只读子资源 | Admin Token、Event | 读取服务端上下文 | 真实 Event 存在；细节可读取 | WORKING_VERIFIED | 否 |
| Human Decision | `POST /editorial/decisions` | Actor、reason、expected previous decision；R3/R4 acknowledgement；archive confirmation | append-only 决定并刷新历史 | 已有独立保存态、成功反馈与服务端刷新；未以审计身份写入 | WIRED_UNVERIFIED | 已补 |
| Merge | `POST /events/{target}/merge` | Actor、source、reason、确认 | 合并状态持久化并刷新 | 已有确认、独立合并态、成功反馈与刷新，并降为低频展开操作；未人工写入 | WIRED_UNVERIFIED | 已补 |
| Split | `POST /events/{id}/split` | Actor、signals、reason | 创建拆分事件 | 路由与调用一致；未人工写入 | WIRED_UNVERIFIED | 补 submitting/success |
| Evidence：核验、备注、信源、Unknown | events evidence POST/PATCH/DELETE | Actor、必填理由或信号 | 持久化 Evidence 状态并 reload | 路由与调用一致；已增加 mutation guard、进行中状态与 reload；未人工写入 | WIRED_UNVERIFIED | 已补前端生命周期 |
| Trend / Score / Override | editorial trend/scores endpoints | Actor、时间窗、评分上下文；AI Provider/Budget/Risk Gate | 创建快照/评分/覆盖并 reload | 路由与调用一致；已增加 mutation guard、进行中状态与 reload；AI 不自动执行 | WIRED_UNVERIFIED | 已补前端生命周期 |
| Card / Pack | drafts card/pack POST | Actor、Card 选择 | 新 Artifact 并 reload | 路由与调用一致；已增加 mutation guard、进行中状态与 reload；未人工写入 | WIRED_UNVERIFIED | 已补前端生命周期 |
| Draft Preview / Apply / Human Revision / Export | drafts endpoints | Actor、Card、Pack、Risk Gate、引用 | 预览或新版本并 reload | 路由与调用一致；已增加 mutation guard、进行中状态与 reload；AI 不自动执行 | WIRED_UNVERIFIED | 已补前端生命周期 |

## 真实 Smoke 结论

| 类别 | 结果 | 说明 |
| --- | --- | --- |
| 后端健康与数据库 | WORKING_VERIFIED | `/health`、`/ready` 均为 200。 |
| Batch A 只读列表 | WORKING_VERIFIED | Instances 1、Sources 1、Runs 6、Accounts 1、Events 1；Schedules/Risk Events 当前为 0。 |
| 写操作、Run、Decision、AI | REAL_SMOKE_BLOCKED | 必须由显式人工 Actor 与所需 confirmation 触发；审计不冒充人类、不自动采集或调用 AI。 |

## Batch A 结论

本次已收口：Instances / Sources 的创建、保存、启停、归档、测试运行与运行记录入口；Schedules 的创建、暂停/恢复、立即运行失败反馈；Runs 的重试/取消防重复提交与失败反馈；Accounts / Risk 的风险解决入口；以及 Workbench 的 Human Decision 与 Merge 提交态、确认、服务端刷新和成功反馈。其余 Workbench 子模块的写操作路径均经契约核对，仍以其本身的 API 异常状态与服务端校验为准。后端接口没有发现本批次必须能力缺失。
