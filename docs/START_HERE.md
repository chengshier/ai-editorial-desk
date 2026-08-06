# AI 编辑部项目开发入口

## 当前阶段

项目已完成 **M1-B：连接器配置管理、运行记录与检查点服务**，下一步建议进入 M1-C。

## 必读文档顺序

1. `DECISIONS.md`
2. `AI编辑部_综合开发实施规划_V1.2.md`
3. `AI编辑部_技术开发文档_V1.2.md`
4. `AI编辑部_PRD_V1.2.md`
5. `CHANGELOG.md`

如文档存在冲突，优先级为：

1. `DECISIONS.md`
2. 综合开发实施规划
3. 技术开发文档
4. PRD

## 已确认决策摘要

- 主仓库为 `ai-editorial-desk`；
- MediaCrawler 作为 `third_party/MediaCrawler` 内置第三方采集模块；
- MVP 通过 Adapter + 子进程调用 MediaCrawler，不要求单独启动 HTTP 服务；
- PostgreSQL + pgvector 通过 Docker Desktop 运行；
- MVP 默认使用云 Embedding，同时保留本地 Provider 接口；
- 平台连接器、AI Provider、模型路由和调度采用可视化配置；
- MediaCrawler 只承担平台采集，不承载事件、AI 编辑或产品工作台；
- 必须实现平台账号风险保护、预算、熔断和人工恢复；
- 不实现验证码破解、指纹伪造、封禁后自动换号或绕过平台限制。

## 已完成基线

### M1-A

- SQLAlchemy 2.x 异步 Engine、Session、FastAPI 依赖和统一 Declarative Base；
- UUID、UTC、JSONB、字符串枚举和数据库异常规范；
- 异步 Alembic 和首份可往返迁移；
- connector definitions、instances、platform accounts、runs、checkpoints、platform risk events 六组基础表；
- `/health`、数据库 `/ready` 和 PostgreSQL 16 + pgvector CI；
- Risk Guard 账号状态、错误分类和风险上下文脱敏。

### M1-B

- 11 个首批 Connector Definition Manifest；
- 幂等 Definition 同步命令和版本更新策略；
- Draft 2020-12 Connector config 与公共 schedule config 校验；
- 普通配置敏感字段递归拒绝；
- Connector Definition 只读管理 API；
- Connector Instance 创建、查询、更新、启停和归档；
- 配置变化版本递增和轻量配置审计；
- Platform Account 创建、查询、引用更新和人工状态转换；
- Connector Run 内部状态服务与管理查询 API；
- Checkpoint 获取、创建和 expected_version 乐观更新；
- Risk Event 查询和人工处理；
- `APP_ADMIN_TOKEN` + `X-Admin-Token` 最小内部管理保护；
- 修改接口 `X-Actor-ID` 操作者记录；
- 第二份独立 migration，不修改 M1-A 初始 migration。

## M1-B 明确边界

本批只建立管理闭环，不执行真实采集。未包含：

- MediaCrawler 子进程执行和平台实跑；
- Scheduler、Worker、队列或定时任务；
- 前端配置中心；
- Secret Manager、明文凭据存储或完整加密系统；
- 完整用户、角色、权限和多租户；
- 完整配置快照、差异页面和一键回滚；
- Signal、Event、去重、聚类、Embedding、AI Provider 和稿件生成；
- 自动账号恢复、自动换号、代理轮换、验证码或反检测能力。

## 下一步 M1-C 建议

1. 建立 Raw Signal、Source 和幂等入库模型；
2. 实现 RSS 与手工 URL 的真实连接器；
3. 建立受控 Collector Runtime，不接 Scheduler；
4. 将 Run、Checkpoint、Risk Guard 串入一次手工触发的任务流程；
5. 增加连接器测试运行接口，但继续禁止凭据回读；
6. 建立采集预算基础模型和任务前检查；
7. 为后续 Scheduler/Worker 明确任务协议和事务边界。

M1-C 仍不应一次进入事件聚类、Embedding 或 AI 稿件生成。

## 开发原则

- 每次只开发一个可验收模块；
- 不擅自扩大当前迭代范围；
- 不把事件聚类、AI 评分、稿件和前端业务写入 MediaCrawler；
- 新增运营配置优先考虑后台可视化；
- 密钥只能进入环境变量或独立凭据存储；
- 风控信号不进入普通重试循环；
- 代码 Definition 只声明注册能力，不冒充已实现、已启用或已验证。
