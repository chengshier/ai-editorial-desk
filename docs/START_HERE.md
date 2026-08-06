# AI 编辑部项目开发入口

## 当前阶段

项目正式进入 **M1：基础设施与项目骨架**。

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

- 主仓库为 `ai-editorial-desk`。
- MediaCrawler 作为 `third_party/MediaCrawler` 内置第三方采集模块。
- MVP 通过 Adapter + 子进程调用 MediaCrawler，不要求单独启动 HTTP 服务。
- PostgreSQL + pgvector 通过 Docker Desktop 运行。
- MVP 默认使用云 Embedding，同时保留本地 Provider 接口。
- 平台连接器、AI Provider、模型路由和调度采用可视化配置。
- MediaCrawler 只吸收五项：断点续采、增量采集、账号/Profile 抽象、签名解耦、有限 HomeFeed 与热榜能力。
- 必须实现平台账号风险保护、预算、熔断和人工恢复。
- 不实现验证码破解、指纹伪造、封禁后自动换号或绕过平台限制。

## 当前开发目标

1. 初始化 Python 工程和目录骨架；
2. 配置 PostgreSQL + pgvector Docker Compose；
3. 建立 FastAPI 基础服务和健康检查；
4. 建立 Connector 基础接口与注册中心；
5. 建立 MediaCrawler Adapter 骨架；
6. 建立账号状态、风险错误与熔断动作基础模型；
7. 加入基础测试、环境变量示例和开发说明。

## 开发原则

- 每次只开发一个可验收模块；
- 不擅自扩大当前迭代范围；
- 不把事件聚类、AI 评分、稿件和前端业务写入 MediaCrawler；
- 新增运营配置优先考虑后台可视化；
- 密钥只能进入环境变量或加密凭据存储；
- 风控信号不进入普通重试循环。
