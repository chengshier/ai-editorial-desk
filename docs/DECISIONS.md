# 项目决策记录

## D-001 仓库结构

采用一个主仓库。MediaCrawler 放在：

```text
third_party/MediaCrawler
```

MVP 阶段由主系统通过 Adapter 启动 MediaCrawler 子进程。

## D-002 模块边界

MediaCrawler 只负责平台采集。事件聚类、AI 评分、证据链、稿件、Provider 管理、工作台和复盘属于主系统。

## D-003 数据库

采用 PostgreSQL + pgvector，通过 Docker Desktop 运行。默认将宿主机 `55432` 映射到容器 `5432`，避免与本机其他数据库环境混淆。

## D-004 AI 策略

MVP 默认使用云 Embedding 和低价云 LLM，同时保留 OpenAI-compatible 与本地 Ollama Provider 接口。

## D-005 配置方式

连接器、AI Provider、任务路由和调度采用可视化配置。YAML/JSON 只用于初始化、导入导出、迁移和备份。

## D-006 MediaCrawler 增强范围

只吸收以下五项：

1. 断点续采；
2. 增量采集；
3. 账号、浏览器 Profile 与可选代理抽象；
4. 签名逻辑解耦；
5. 有限 HomeFeed 与热榜补充发现。

不以复刻 Pro 为目标。

## D-007 平台账号风控

遇到验证码、权限拒绝、403、406、429、`account blocked`、检测到自动化或明确账号限制时，停止任务并进入人工检查，不自动反复登录或继续重试。

## D-008 MVP 运行形态

初期保持一个产品入口。MediaCrawler 按采集任务临时启动子进程，任务结束后退出，不要求运营人员维护第二套后台。

## D-009 Connector Definition 所有权

Connector Definition 由代码 Manifest 管理，并通过幂等命令同步到数据库：

- 使用 `connector_type + platform` 作为稳定定位键；
- 代码拥有 `display_name`、`capabilities`、`config_schema`、`ui_schema` 和 `implementation_version`；
- 数据库中的 `is_enabled` 属于运营状态，后续同步不得覆盖；
- Definition 注册只表示系统已声明该来源，不等于实现、启用或验证；
- Definition 同步不写入 Alembic migration，避免迁移依赖运行时业务逻辑。

## D-010 M1-B 管理接口保护与审计

在完整用户和 RBAC 建立前，`/api/v1/admin/*` 使用环境变量 `APP_ADMIN_TOKEN` 和请求头 `X-Admin-Token` 进行最小内部保护，修改接口额外要求 `X-Actor-ID`。

该机制仅用于内部开发阶段，不宣称为完整认证系统。配置修改使用轻量 `configuration_change_logs` 记录脱敏前后数据；M1-B 不实现完整快照回滚。
