# AI 编辑部项目开发入口

## 当前阶段

- **M1-A：已完成**；
- **M1-B：已完成**；
- **M1-C：已完成开发与 CI 验收，当前等待 PR 合并**；
- 下一步进入 **M1-D：完成 M1 剩余范围**，不直接进入 M2。

## 必读文档顺序

1. `DECISIONS.md`
2. `AI编辑部_综合开发实施规划_V1.2.md`
3. `AI编辑部_技术开发文档_V1.2.md`
4. `AI编辑部_PRD_V1.2.md`
5. `CHANGELOG.md`

冲突优先级：DECISIONS → 综合开发实施规划 → 技术开发文档 → PRD。

## 已完成基线

### M1-A

- Async SQLAlchemy、统一 ORM Base、UUID、UTC、JSONB 和异步 Alembic；
- Definition、Instance、Account、Run、Checkpoint、Risk Event 基础表；
- PostgreSQL 16 + pgvector CI 和 Risk Guard 基础模型。

### M1-B

- 11 个代码 Definition Manifest 与幂等同步；
- JSON Schema 配置校验、实例与账号管理、Run/Checkpoint 服务；
- Admin Token、Actor、配置审计与风险事件人工处理。

### M1-C

- 新增 `sources`、`raw_signals`、`collection_budgets`、`collection_budget_usage`；
- 新增独立 `20260806_0003` migration，不修改 M1-A/M1-B migration；
- Connector 统一输出独立 RawSignal 领域模型；
- URL 规范化、稳定内容哈希和 v1 幂等键；
- PostgreSQL `ON CONFLICT` Raw Signal 并发幂等写入；
- RSS 2.0 / Atom、ETag、Last-Modified、304 和有界网络请求；
- 手工 URL 导入、有限页面提取和逐跳 SSRF 防护；
- 明确 Implementation Registry，仅 RSS 与手工 URL 可运行；
- CollectionTask 可 JSON 序列化并支持 manual/test/scheduled/retry；
- Run 使用数据库条件更新原子领取和终态转换；
- 数据库预算预留、自然日 usage 与并发限制；
- Runtime 将预检、网络、分批入库、Checkpoint、终态和预算结算拆为短事务；
- Risk Guard 接入运行时，普通 HTTP 错误与平台风险分开；
- Source、Raw Signal、Budget、test-run 和 manual-import 管理 API；
- 全部网络测试使用 Fixture、MockTransport 或不抓取模式。

## 当前真实实现状态

- RSS：registered=true、implemented=true、enabled 取数据库状态、validated=false；
- 手工 URL：registered=true、implemented=true、enabled 取数据库状态、validated=false；
- MediaCrawler 七个平台、Reddit、热榜：仅 registered，尚未 implemented/validated。

Definition、Implementation Registry 和运营启停是三个独立概念，不得混用。

## 事务与安全边界

- 网络请求不能占用长数据库事务；
- Run 领取、每批信号写入、Checkpoint 推进、Run 终态和预算结算分别使用短事务；
- Checkpoint 只跟随已提交信号推进；入库失败不得推进；
- Raw Signal 不存 Cookie、Authorization、访问 Token 或完整请求头；
- 手工 URL 拒绝 localhost、私网、IPv6 本地地址、链路本地、多播、保留和云元数据地址；
- Redirect 每一跳重新解析并验证；
- 不自动换号、切换代理、处理验证码或绕过平台限制。

## M1-C 明确未做

- Scheduler、APScheduler、Celery、Redis Worker；
- 前端配置中心；
- MediaCrawler 子进程和平台实跑；
- 浏览器登录、Cookie 扫码、HomeFeed 和评论采集；
- Signal 之后的 Event、聚类、Embedding、AI Provider、评分、证据和稿件；
- 自动恢复账号、代理轮换、验证码破解和指纹伪造。

## M1-D 建议：完成 M1 剩余范围

1. Scheduler 与数据库调度状态；
2. 崩溃任务识别、人工重试与 Run 调试；
3. 至少一个无需登录、公开、低风险的国内热榜入口；
4. 基础连接器配置 Web 页面；
5. JSON Schema 动态表单基础组件；
6. Run 日志页面；
7. Checkpoint 调试 API/页面；
8. Risk Event 和账号暂停/人工恢复操作页面；
9. RSS、手工 URL、热榜的低量真实验收和 validated 状态管理；
10. 完成 M1 总体验收后才进入 M2。

**Event、EventSignal、Embedding、去重、事件聚类以及人工合并/拆分不属于 M1-D；这些能力按正式路线在 M3 进入。**

## 开发原则

- 每次只开发一个可验收模块；
- 不擅自扩大迭代范围；
- 代码 Definition 只表示注册，不冒充已实现或已验证；
- Connector 不创建 ORM、不提交事务、不承担聚类或 AI 判断；
- 密钥只进入环境变量或独立凭据存储；
- 风控信号不进入普通重试循环；
- 不修改第三方 MediaCrawler 平台业务源码来承载主系统职责。
