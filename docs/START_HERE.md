# AI 编辑部项目开发入口

## 当前阶段

- **M1-A：已完成**；
- **M1-B：已完成**；
- **M1-C：已完成**；
- **M1-D：已完成开发与 CI 验收，PR #6 等待合并**；
- **M1：已完成工程开发与 CI 验收**；
- 下一阶段：**M2**。

PR #6 合并后，`main` 才正式具备完整 M1 基线。当前不要在 M1-D 分支继续开发 M2。

## 必读文档顺序

1. `DECISIONS.md`
2. `M1_ACCEPTANCE_REPORT.md`
3. `AI编辑部_综合开发实施规划_V1.2.md`
4. `AI编辑部_技术开发文档_V1.2.md`
5. `AI编辑部_PRD_V1.2.md`
6. `CHANGELOG.md`

冲突优先级：DECISIONS → 综合开发实施规划 → 技术开发文档 → PRD。

## M1 已完成基线

### M1-A

- Async SQLAlchemy、统一 ORM Base、UUID、UTC、JSONB 和异步 Alembic；
- Definition、Instance、Account、Run、Checkpoint、Risk Event 基础表；
- PostgreSQL 16 + pgvector CI 和 Risk Guard 基础模型。

### M1-B

- 11 个代码 Definition Manifest 与幂等同步；
- JSON Schema / UI Schema 与后端配置校验；
- Instance、Platform Account、Run、Checkpoint 管理；
- Admin Token、Actor、配置审计与风险事件人工处理。

### M1-C

- Source、Raw Signal、Collection Budget 与 usage；
- RSS 2.0 / Atom 与手工 URL 真实基础 Connector；
- URL 规范化、SSRF/Redirect 防护、稳定 v1 幂等键；
- PostgreSQL `ON CONFLICT` 并发幂等写入；
- CollectionTask、Collector Runtime、Run 原子领取；
- 数据库预算预留与并发限制；
- Checkpoint 只跟随已提交信号推进；
- Risk Guard 接入 Runtime，普通 HTTP 错误与平台风险分离；
- Source、Raw Signal、Budget、test-run、manual-import API。

### M1-D

- PostgreSQL 持久化 `collection_schedules`、时间槽 Trigger 和 Scheduler heartbeat；
- 数据库 Lease、同一时间槽唯一约束、Lease 过期恢复；
- asyncio Scheduler 复用现有 CollectionTask / Collector Runtime；
- stale RUNNING Run 识别、人工失败/取消、retry 新 Run 与 parent_run_id；
- retry 重新经过 Budget 与 Risk Guard，不做无限自动 retry；
- Run Debug 详情、Checkpoint 查询与 expected_version 高风险 reset；
- Checkpoint reset Actor/reason/审计，并保证不删除 Raw Signal；
- 国内公开低风险百度实时热榜 Hotlist Connector；
- Connector Validation NOT_TESTED/PASSED/FAILED/EXPIRED 与版本过期语义；
- PASSED 验真绑定人工成功 Test/Manual Run 证据，CI/Mock 不自动设置 validated；
- React + Vite + TypeScript 基础连接器工作台；
- JSON Schema 动态配置表单；
- Definitions、Instances、Sources、Schedules、Runs、Checkpoints、Accounts/Risk 页面；
- Instance/Source 新建、编辑、启停/归档与 Test Run，Instance 支持 Run Now；
- M1 总体验收报告：`M1_ACCEPTANCE_REPORT.md`。

## 当前 Connector 状态语义

- RSS：registered=true、implemented=true；enabled 取数据库运营状态；validated 只有人工真实低量 Smoke 记录 PASSED 后才为 true；
- Manual URL：同上；
- Hotlist：M1-D 已实现 `baidu_realtime`，同样需要人工真实低量 Smoke 后才写 PASSED；
- MediaCrawler 七个平台、Reddit：仍未进入真实运行验收，不得冒充 implemented/validated。

Definition 注册、Implementation Registry、运营启停和真实 validated 是四个独立概念。

## M1 事务、并发与安全边界

- Scheduler 只负责触发，不重新实现 Connector 执行逻辑；
- Scheduler Lease 和时间槽去重由 PostgreSQL 保证，不依赖纯内存 mutex；
- 网络请求不能占用长数据库事务；
- Run 领取、预算、信号批次、Checkpoint、终态分别使用受控短事务；
- Raw Signal 以数据库唯一约束作为最终并发幂等保护；
- stale Run 不自动恢复成 RUNNING，不自动无限重试；
- retry 创建新 Run，旧 Run 保持历史终态；
- Checkpoint reset 使用 expected_version 乐观锁、Actor、reason 与审计；
- RSS、Manual、Hotlist 网络边界拒绝 localhost、私网、链路本地、云元数据地址与危险 Redirect；
- 明确平台风险不进入普通重试循环；
- 不自动换号、代理轮换、处理验证码或绕过平台限制；
- Web/API 不显示 Cookie、Token、Authorization、API Key、credential_ref/browser_profile_ref 原值；
- 前端 Schema 校验仅改善体验，后端 JSON Schema 校验始终是最终权威。

## M1 最终 CI

PostgreSQL 16 + pgvector：

- Ruff：通过；
- Mypy：通过，99 个 Python 源文件无类型错误；
- Pytest：120 passed；
- Alembic：`upgrade head → downgrade -1 → upgrade head → downgrade base → upgrade head` 通过；
- Connector Definition 连续同步两次，第二次保持 11 条 unchanged、0 created、0 updated、0 failed。

Web：

- lint：通过；
- typecheck：通过；
- unit tests：6 个 test files、8 tests passed；
- production build：通过。

详细对应代码、测试、状态与限制见 `M1_ACCEPTANCE_REPORT.md`。

## 真实 Smoke 与 validated

CI 不连接真实外部网站，所以 CI 全绿不等于运营数据库已经存在 PASSED validation。

真实验收流程是：管理员以低量 Test Run / Manual Import 运行 RSS、Manual URL 或 Hotlist；运行仍受 Budget、Risk Guard、SSRF、Checkpoint 和幂等约束；得到 SUCCEEDED Test/Manual Run 后，才能携带 Actor 和 `run_id` 写 PASSED。实现版本变化后旧验真按 EXPIRED 解释。

不要通过 CI fixture/mock 自动设置真实 validated=true。

## 下一阶段边界

下一阶段只进入 **M2**，不要把后续能力倒灌回 M1-D。

M1 没有实现：

- Event / EventSignal；
- Embedding、pgvector 相似检索、文本近似去重与事件聚类；
- 人工合并/拆分事件；
- AI Gateway / AI Provider / AI 评分；
- 证据提取与稿件生成；
- MediaCrawler 七个平台真实运行与五项增强；
- Redis / Celery / 大规模 Worker 集群。

Event、Embedding 和事件聚类仍属于后续 M3 范围。

## 开发原则

- 每次只开发一个可验收模块；
- 不擅自扩大迭代范围；
- Definition 只表示注册，不冒充已实现或已验证；
- Connector 不创建 ORM、不提交事务、不承担聚类或 AI 判断；
- 密钥只进入环境变量或独立凭据存储；
- 风控信号不进入普通 retry；
- 不修改第三方 MediaCrawler 平台业务源码来承载主系统职责。
