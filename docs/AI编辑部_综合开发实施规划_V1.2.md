# AI 编辑部系统综合开发实施规划 V1.2

> 文档状态：开发总纲 / 已补充 MediaCrawler 五项增强与平台账号风险保护  
> 编写日期：2026-08-04  
> 关联文档：`AI编辑部_PRD_V1.2.md`、`AI编辑部_技术开发文档_V1.2.md`  
> 适用范围：从项目启动、MVP、V1、V1.5、V2 到稳定运行阶段  
> 核心原则：本文档描述完整产品路线，不只描述第一批开发任务；每一阶段均明确目标、范围、平台、技术任务、交付物、验收标准、依赖和暂缓事项。

---

## 1. 文档目的

本文档是 AI 编辑部系统的综合开发实施总纲，用于统一以下事项：

1. 项目为什么做、为谁做、最终要解决什么问题；
2. 系统完整能力边界与长期产品形态；
3. 各平台如何通过可插拔连接器逐步接入；
4. MediaCrawler 在系统中的定位与使用方式；
5. AI、Embedding、数据库、任务调度和前端如何协作；
6. 从第一批到后续各批次的开发顺序、依赖关系和验收标准；
7. 哪些能力首期启用、哪些能力已适配但暂不启用、哪些能力需要后续重新开发；
8. 项目在开发、测试、实跑、稳定运行和未来商业化时分别需要注意什么。

本文档既是产品路线图，也是开发执行依据。后续每个迭代可以再从本总纲中拆出 Sprint 任务，但不得脱离本总纲单独堆功能。

---

## 2. 项目定位与用途分析

### 2.1 产品定位

AI 编辑部不是传统新闻聚合器，也不是全自动营销号生成器，而是一套面向短视频创作者的：

- 多平台事件发现系统；
- 信息整理与事实链构建系统；
- 流量价值与内容价值判断系统；
- 编辑选题和稿件生产辅助系统；
- 发布后复盘与知识沉淀系统。

系统每天从国内外平台读取公开信号，将零散帖子、视频、媒体报道、评论和官方回应聚合成“事件”，再依据账号定位筛选最值得讲的内容，最终输出可供人工审核和发布的资料包。

### 2.2 账号内容定位

账号不是单一新闻号，也不是单一娱乐号，而是“每天告诉用户几件值得知道的事”。内容可以覆盖：

- 社会民生；
- 国际社会奇闻；
- 娱乐、综艺、影视和人物；
- 科技、AI 与互联网；
- 食品安全和消费安全；
- 灾害、天气和公共事件；
- 网络传闻与真假拆解；
- 普通人故事、反差故事和情绪价值内容。

内容选择以播放、完播、点赞、评论、转发和关注增长为目标，但必须保留来源、区分事实与传闻，并设置风险门槛。

### 2.3 核心用户价值

系统最终帮助创作者做到：

1. 比普通用户看到更广的信息面；
2. 比单纯刷热榜更早发现小范围发酵的事件；
3. 将同一事件的不同来源自动归并；
4. 快速识别信息差、情绪张力、画面价值和普通人相关度；
5. 判断哪些事件适合合集、快讲或深挖；
6. 生成事实链、待核实项、素材清单和口播稿；
7. 记录哪些选题被采用、哪些被放弃、哪些后来爆发；
8. 用真实发布数据逐步校准选题模型。

### 2.4 系统不能解决的问题

系统不能发现尚未上传到互联网、没有进入任何监控源的事件。系统所解决的是：

> 已经在互联网某个角落出现，但创作者尚未知道、主流用户尚未普遍刷到的事件。

因此系统重点是扩大观测面、提高信号发现率和降低人工筛选成本，而不是承诺“发现全世界所有未知事件”。

---

## 3. 已确认的总体决策

### 3.1 MediaCrawler 使用策略

1. 项目开发和内部使用阶段可直接采用 MediaCrawler；
2. MediaCrawler 作为独立的国内社交平台采集服务接入，不承载事件聚类、AI 编辑和前端业务；
3. 其当前支持的平台全部在系统中注册为连接器；
4. 平台是否启用由配置控制，不因首期未启用就视为“未接入”；
5. 系统核心不得依赖 MediaCrawler 的内部表结构，以便未来替换、升级或增加其他实现；
6. 若未来项目用途、账号变现方式或分发方式发生变化，需重新核对许可证和平台条款。

### 3.2 国内平台策略

MediaCrawler 已支持的平台统一纳入连接器注册中心：

- 微博；
- B站；
- 知乎；
- 抖音；
- 小红书；
- 快手；
- 百度贴吧。

首期不是“只开发微博和B站”，而是：

- 七个平台均完成统一适配注册；
- 第一批默认启用微博、B站、知乎；
- 抖音、小红书、快手、贴吧按阶段打开；
- 每个平台独立配置账号、登录态、频率、关键词、评论抽样和失败重试。

### 3.3 AI 与 Embedding 策略

1. AI Gateway 采用供应商无关设计；
2. MVP 默认使用云端 Embedding，减少本地部署负担；
3. 保留本地 Embedding Provider，可随时切换；
4. 低价云模型负责抽取、评分和常规稿件；
5. 更强模型仅处理 TOP 事件、复杂争议和最终深稿；
6. 模型、价格和供应商不得写死在业务代码中；
7. 每次调用记录 Token、费用、耗时、Prompt版本和采用结果；
8. Embedding 模型变更需要版本化，必要时执行全量重建向量。

### 3.4 数据库与部署策略

1. 主数据库采用 PostgreSQL + pgvector；
2. Windows 本地通过 Docker Desktop 运行 PostgreSQL；
3. 为避免与现有数据库混淆，推荐映射宿主机端口 `55432` 到容器内 `5432`；
4. 本机 MySQL、SQL Server 和 PostgreSQL 可以并存；
5. MVP 不强制引入 Redis、MinIO 和复杂消息队列；
6. V1 后按并发、数据量和媒体存储需求增加基础设施；
7. 涉及扫码登录和浏览器自动化的平台可继续运行在 Windows 采集节点。

### 3.5 初期产品形态

- 主栏目：每日信息差合集；
- 辅助栏目：单条事件快讲、真假拆解、娱乐综艺、食品与消费安全、深挖还原；
- 发布频率：初期每天一条主内容，特别强事件可增加一条；
- 前端首期：事件列表、详情、来源链、评分、采用/观察/放弃、合并/拆分、Markdown 导出；
- 自动发布：不在 MVP 和 V1 的核心范围内；
- 发布数据回流：先支持手工填写和 CSV 导入，后续再接平台接口。

### 3.6 可视化配置原则

1. 平台连接器、采集频率、关键词、账号、评论抽样、Provider、模型路由、预算和调度均通过可视化后台管理；
2. YAML/JSON 只作为初始化、批量导入导出、环境迁移、备份和灾难恢复格式；
3. 普通运营配置保存到数据库，不要求修改代码或重启主服务；
4. 每种连接器通过能力声明和 JSON Schema 驱动动态表单；
5. API Key、Cookie、OAuth Token 和代理密码与普通配置分离加密存储；
6. 所有配置修改保留版本、操作者、差异和回滚能力；
7. 新增 IG、X、TikTok 或其他平台时，优先增加连接器定义与 Schema，而不是修改核心工作台。

### 3.7 MediaCrawler 增强范围

仅吸收以下五项：

1. 断点续采；
2. 增量采集；
3. 账号、浏览器 Profile 与可选代理的统一抽象；
4. 签名逻辑解耦；
5. 首页流与热榜对未知事件发现的补充。

其中热榜优先作为独立连接器建设；HomeFeed 放在 V1 低频灰度。明确不做 Pro 全量复刻、全面去除 Playwright、通用桌面下载器、采集器内 AI Agent、全自动账号/IP轮换和验证码破解。

### 3.8 平台账号风险控制原则

1. 账号风险保护是采集底座能力，不是后期附加功能；
2. 正式发布账号、个人主账号与采集测试账号完全分离；
3. 每个账号固定绑定浏览器 Profile，并记录状态、预算和风险事件；
4. 验证码、权限拒绝、403/406/429、`account blocked` 和自动化检测属于不可自动重试风险；
5. 风险触发后立即停止任务、保存断点、暂停账号或平台队列并转人工；
6. 不通过自动换号、代理轮换、指纹伪造或持续重试绕过平台限制；
7. 小红书、抖音等高风险平台首期优先用于候选事件补全；
8. 风险控制只能降低概率，不能承诺账号绝对安全。

---

## 4. 完整能力地图

系统完整能力分为九层。

### 4.1 信号源管理层

管理：

- 平台；
- RSS / Atom Feed；
- 热榜；
- 指定账号；
- 板块 / 社区；
- 关键词；
- 地区和语言；
- 用户手工 URL；
- 后续投稿、邮件或浏览器插件入口。

### 4.2 连接器与采集层

支持：

- Feed 模式；
- 热榜模式；
- 指定账号模式；
- 关键词搜索模式；
- 内容详情模式；
- 评论抽样模式；
- 增量游标；
- 失败重试；
- 健康检查；
- 登录状态管理；
- checkpoint 与断点续采；
- 增量水位；
- 账号状态机；
- 请求预算与风险熔断；
- 签名 Provider；
- 受控 HomeFeed。

### 4.3 数据标准化层

处理：

- 不同平台字段统一；
- 时间统一；
- 语言识别；
- URL 规范化；
- 文本清洗；
- 互动指标映射；
- 图片、视频和字幕元数据；
- 内容哈希和媒体哈希。

### 4.4 去重与事件聚类层

支持：

- URL 去重；
- 精确文本哈希；
- SimHash / MinHash 近似去重；
- Embedding 语义召回；
- 跨语言相似度；
- 时间、地点、人物和媒体哈希联合判断；
- LLM 边界样本判断；
- 人工合并和拆分。

### 4.5 趋势与信息差层

计算：

- 互动增长速度；
- 独立来源数量；
- 平台数量；
- 同步出现程度；
- 海外与国内信号差；
- 新增事实或新增画面；
- 评论情绪聚集；
- 事件生命周期阶段。

### 4.6 证据与事实层

区分：

- 原始视频；
- 媒体报道；
- 官方回应；
- 企业声明；
- 网友评论；
- 推测；
- 传闻；
- 反驳或更正。

每条事实必须绑定来源，不能只由模型生成。

### 4.7 AI 编辑层

包括：

- 事件要素抽取；
- 跨来源摘要；
- 风险等级；
- 流量价值评分；
- 信息差判断；
- 栏目适配；
- 推荐时长；
- 切入角度；
- 标题和封面文案；
- 30 秒、90 秒和 2—3 分钟稿件；
- 评论区互动问题。

### 4.8 编辑工作台层

支持：

- 今日候选池；
- TOP20 / TOP10 / TOP5；
- 事件详情；
- 来源时间线；
- 事实和待核实项；
- 人工评分修改；
- 采用、观察、放弃和归档；
- 稿件版本编辑；
- Markdown 导出；
- 后续多人权限和审批。

### 4.9 复盘与知识库层

保存：

- 事件；
- 稿件版本；
- 发布平台和链接；
- 播放、完播、点赞、评论、转发和涨粉；
- AI 推荐结果；
- 人工选择结果；
- 被放弃后爆发的错题；
- 来源命中率；
- 栏目和标题模板表现。

---

## 5. 总体技术架构

```mermaid
flowchart TB
    subgraph Source[数据源]
      RSS[RSS/新闻]
      Hot[热榜]
      Reddit[Reddit]
      MC[MediaCrawler七个平台]
      Overseas[YouTube/X/IG/TikTok]
      Manual[手工URL/文件]
    end

    subgraph Collector[采集层]
      Registry[Connector Registry]
      Scheduler[Scheduler]
      Gateway[Collector Gateway]
      Health[Connector Health]
      Checkpoint[Checkpoint/增量水位]
      RiskGuard[账号风险保护]
    end

    subgraph Data[数据层]
      Raw[Raw Signal]
      Normalize[Normalize]
      Dedup[Deduplicate]
      Vector[Embedding]
      Cluster[Event Cluster]
      Evidence[Evidence & Claims]
    end

    subgraph AI[AI层]
      Router[AI Gateway]
      Score[Editorial Score]
      Risk[Risk Gate]
      Draft[Editorial Pack]
    end

    subgraph Product[产品层]
      API[FastAPI]
      Web[Editorial Workbench]
      Export[Markdown/CSV]
      Feedback[Performance Feedback]
    end

    Source --> Registry
    Registry --> Scheduler
    Scheduler --> Gateway
    Gateway --> RiskGuard
    RiskGuard --> Checkpoint
    Checkpoint --> Raw
    Raw --> Normalize --> Dedup --> Vector --> Cluster --> Evidence
    Evidence --> Router --> Score --> Risk --> Draft
    Draft --> API --> Web
    Web --> Export
    Feedback --> Score
```

### 5.1 架构约束

1. 连接器不得直接写事件评分；
2. AI 不得直接写入“已确认事实”，必须带来源 ID；
3. 平台名称不得写死在核心业务枚举中；
4. 模型名称不得写死在业务服务中；
5. 单一平台失败不得阻塞其他平台；
6. 采集、处理、AI 和前端可独立运行；
7. 所有任务必须幂等，可安全重试；
8. 原始链接和采集时间必须保留。

---

## 6. 推荐技术栈

| 模块 | MVP | 后续扩展 |
|---|---|---|
| 后端语言 | Python 3.11+ | 保持 Python 主栈 |
| API | FastAPI | 多服务拆分 |
| ORM | SQLAlchemy 2.x | 保持 |
| 数据验证 | Pydantic v2 | 保持 |
| 数据库 | PostgreSQL + pgvector | 读写分离或托管数据库 |
| 调度 | APScheduler / asyncio | Celery、ARQ 或任务平台 |
| 队列 | 首期不强制 | Redis + Worker |
| 前端 | React + Vite | 完整管理后台 |
| 媒体存储 | 本地缓存目录 | MinIO / S3 |
| Embedding | 云 API 默认 | 本地模型或多 Provider |
| LLM | OpenAI 兼容 API | 多模型路由和降级 |
| 本地模型 | Ollama 可选 | llama.cpp / GPU 服务 |
| 语音转写 | 候选事件按需调用 | 独立 ASR Worker |
| 部署 | Windows + Docker Desktop | Docker Compose / 云服务器 |
| 监控 | 结构化日志 | Prometheus / Grafana / Sentry |

---

## 7. 代码仓库规划

```text
ai-editorial-desk/
├── apps/
│   ├── api/                         # FastAPI 主服务
│   ├── web/                         # 编辑工作台
│   ├── worker/                      # 数据处理与 AI Worker
│   └── scheduler/                   # 定时任务
├── packages/
│   ├── connectors/
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── rss/
│   │   ├── hotlist/
│   │   ├── reddit/
│   │   ├── mediacrawler/
│   │   │   ├── adapter.py
│   │   │   ├── mapper.py
│   │   │   └── platforms/
│   │   ├── youtube/
│   │   ├── x/
│   │   ├── instagram/
│   │   ├── tiktok/
│   │   ├── douban/
│   │   └── manual/
│   ├── collector_runtime/
│   │   ├── checkpoint.py
│   │   ├── incremental.py
│   │   ├── risk_guard.py
│   │   ├── budgets.py
│   │   ├── accounts.py
│   │   └── signature_provider.py
│   ├── pipeline/
│   │   ├── normalize.py
│   │   ├── deduplicate.py
│   │   ├── embedding.py
│   │   ├── clustering.py
│   │   ├── trend_detection.py
│   │   ├── evidence.py
│   │   └── lifecycle.py
│   ├── editorial/
│   │   ├── scoring.py
│   │   ├── risk.py
│   │   ├── format_router.py
│   │   ├── prompts/
│   │   └── schemas.py
│   ├── ai_gateway/
│   │   ├── base.py
│   │   ├── openai_compatible.py
│   │   ├── ollama.py
│   │   ├── router.py
│   │   ├── cost.py
│   │   └── cache.py
│   ├── media/
│   │   ├── subtitles.py
│   │   ├── asr.py
│   │   ├── keyframes.py
│   │   └── ocr.py
│   ├── domain/
│   │   ├── source.py
│   │   ├── signal.py
│   │   ├── event.py
│   │   ├── evidence.py
│   │   ├── score.py
│   │   ├── draft.py
│   │   └── publication.py
│   └── common/
│       ├── config.py
│       ├── logging.py
│       ├── security.py
│       └── exceptions.py
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   └── evaluation/
├── scripts/
├── docker/
├── docs/
├── .env.example
├── docker-compose.yml
└── pyproject.toml
```

---

## 8. 连接器统一规范

### 8.1 连接器能力模型

每个连接器声明自己支持哪些能力，而不是假设所有平台能力一致。

```yaml
connector: instagram_official
capabilities:
  feed: false
  hotlist: false
  search: limited
  account_monitoring: true
  detail: true
  comments: authorized_only
  realtime: webhook_optional
  official_api: true
  requires_oauth: true
```

### 8.2 基础接口

```python
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

@dataclass(slots=True)
class CollectRequest:
    source_id: str
    mode: str  # feed/hotlist/search/account/detail/comments
    query: str | None = None
    target_ids: list[str] | None = None
    cursor: str | None = None
    since: datetime | None = None
    limit: int = 100

@dataclass(slots=True)
class RawSignal:
    platform: str
    external_id: str
    url: str
    title: str | None
    text: str | None
    author_id: str | None
    author_name: str | None
    published_at: datetime | None
    metrics: dict[str, int | float]
    media: list[dict]
    raw_payload: dict

class BaseConnector(ABC):
    connector_type: str

    @abstractmethod
    async def health_check(self) -> dict:
        ...

    @abstractmethod
    async def collect(self, request: CollectRequest) -> AsyncIterator[RawSignal]:
        ...

    @abstractmethod
    async def fetch_detail(self, external_id: str) -> RawSignal:
        ...
```

### 8.3 平台内部配置结构与导入导出示例

以下 YAML 是系统内部序列化格式，不是日常操作入口。实际启用、停用、账号维护、频率调整和评论抽样均通过可视化配置中心完成。

```yaml
sources:
  - id: weibo_hot_and_media
    connector: mediacrawler
    platform: wb
    enabled: true
    modes: [search, account, detail]
    cadence_minutes: 30
    max_items: 100
    comment_sample_limit: 30

  - id: douyin_monitored_accounts
    connector: mediacrawler
    platform: dy
    enabled: false
    modes: [account, detail]
    cadence_minutes: 60
    max_items: 50

  - id: reddit_weird_and_news
    connector: reddit
    enabled: true
    mode: feed
    targets: [NotTheOnion, todayilearned, worldnews]
    cadence_minutes: 30
    max_items: 100
```

### 8.4 可视化连接器管理中心

连接器中心至少提供：

- 卡片/表格列表：名称、平台、连接器类型、启用状态、健康状态、最近运行、下次运行、采集数量、最近错误；
- 新建、复制、编辑、归档、删除和批量启停；
- 测试连接、立即运行、查看运行日志；
- 设置采集模式、关键词、账号、板块、Feed、地区、语言、时间窗口、最大条数和评论抽样；
- 管理扫码登录、Cookie、OAuth、API Key、代理和凭据过期状态；
- 显示 `registered / implemented / enabled / validated` 四级状态；
- YAML/JSON 导入导出、差异预览、配置版本和回滚。

### 8.5 Schema 驱动的动态表单

每个 Connector Definition 注册：

```text
connector_type
platform
display_name
capabilities
config_schema
ui_schema
implementation_version
```

前端根据 `config_schema` 自动生成字段，根据 `capabilities` 隐藏不支持的模式。例如 Reddit 展示 Subreddit 和 `new/rising/hot`，微博展示关键词、账号、详情和评论，Instagram 展示 OAuth 授权与账号范围。

特殊能力通过专属组件扩展：

- MediaCrawler 扫码登录；
- OAuth 跳转和回调；
- 多账号选择器；
- 凭据替换；
- 代理测试；
- 节点选择。

### 8.6 连接器配置存储和热更新

配置写入数据库并生成版本：

```text
前端表单
→ Schema校验
→ 敏感字段拆分加密
→ 保存配置快照
→ Scheduler重新加载
→ 健康检查
→ 新任务采用新配置
```

正在执行的任务不被强制中断；新配置对下一次任务生效。保存失败或健康检查失败时，保留上一有效版本。

### 8.7 连接器安全策略 Schema

所有需要登录态或浏览器自动化的连接器都附带 `risk_policy`：

```yaml
risk_policy:
  account_id: xhs_test_01
  browser_profile_id: xhs_profile_01
  concurrency: 1
  max_items_per_run: 20
  max_comments_per_item: 10
  max_runs_per_day: 3
  sub_comments_enabled: false
  auto_relogin: false
  on_captcha: pause_and_review
  on_permission_denied: pause_and_review
  on_account_restricted: disable_account
```

该配置由可视化后台管理。平台 Definition 可以给出更保守的默认值，但用户不能把明确账号限制配置为“无限重试”。

---

## 9. 平台完整接入规划

### 9.1 平台状态分类

每个平台使用四种状态：

- `registered`：已在连接器注册中心定义；
- `implemented`：连接器已实现；
- `enabled`：当前环境正在运行；
- `validated`：经过连续实跑并达到验收标准。

“暂不启用”不等于“暂不开发”，必须在文档和后台中明确区分。

### 9.2 MediaCrawler 平台

| 平台 | 接入状态规划 | 第一批默认 | 核心用途 | 后续增强 |
|---|---|---:|---|---|
| 微博 | 注册、实现、启用、验证 | 是 | 热议、明星、媒体、官方回应 | 热搜、超话、账号分组 |
| B站 | 注册、实现、启用、验证 | 是 | 视频线索、长内容、评论观点 | 字幕、评论时间点 |
| 知乎 | 注册、实现、启用、验证 | 是 | 背景解释、争议问题 | 高赞回答摘要 |
| 抖音 | 注册、实现，第二阶段低量启用 | 否 | 候选事件补全、现场画面 | 受控HomeFeed、评论抽样与风险熔断 |
| 小红书 | 注册、实现，第二阶段低量启用 | 否 | 候选事件补全、消费与生活方式 | 图片OCR、严格预算与风险熔断 |
| 快手 | 注册、实现，第二阶段启用 | 否 | 地方生活、下沉市场、现场事件 | 地区来源分组 |
| 百度贴吧 | 注册、实现，第二阶段启用 | 否 | 游戏、影视、兴趣圈早期讨论 | 吧内新帖与热帖 |

### 9.3 国内其他来源

| 来源 | 计划阶段 | 用途 | 接入方式 |
|---|---|---|---|
| 国内热榜聚合 | 第一阶段 | 无关键词发现 | 自建轻量连接器 |
| RSS / 新闻最新页 | 第一阶段 | 媒体、地方新闻、科技 | RSS优先，页面补充 |
| 手工 URL | 第一阶段 | 临时线索快速入库 | 通用解析器 |
| 豆瓣 | 第三阶段 | 影视和书影音讨论 | 独立低频连接器 |
| 节目/影视官方账号 | 第二阶段 | 综艺和影视素材 | 账号监控配置 |
| 用户投稿 | 第四阶段 | 扩大线索来源 | 表单/邮件/插件 |

### 9.4 海外平台

| 平台 | 计划阶段 | 核心价值 | 主要限制 | 推荐策略 |
|---|---|---|---|---|
| Reddit | 第一阶段 | 奇闻、科技、社会、讨论苗头 | API政策和数据保留 | 板块 new/rising/hot |
| 新闻 RSS | 第一阶段 | 可核验来源、地方新闻 | Feed质量不一 | 建可信来源库 |
| YouTube | 第三阶段 | 长视频、Shorts、频道追踪 | API配额、字幕版权 | 频道优先，搜索补充 |
| X | 第三阶段 | 记者、媒体、科技、娱乐早信号 | 套餐和配额变化 | 账号列表+有限查询 |
| Instagram / IG | 第三阶段 | 明星、Reels、视觉文化 | 官方公共发现能力有限 | 监控账号+手工URL+合规数据源 |
| TikTok | 第三/四阶段 | 海外短视频趋势 | 官方能力和资格限制 | 独立连接器，不复用抖音实现 |
| Threads | 第四阶段 | 公众人物和趋势补充 | API能力变化 | 观察后接入 |
| Telegram公开频道 | 第四阶段 | 地区和行业消息 | 风险与真实性 | 白名单频道，严格证据分级 |
| 海外地方新闻站 | 第三阶段 | 本地奇闻和早期新闻 | 站点差异大 | RSS模板+站点适配器 |

### 9.5 新平台接入流程

任何新平台必须经过：

1. 用途评估；
2. 官方 API / RSS / Feed 调研；
3. 合规和授权评估；
4. 能力声明；
5. Connector 实现；
6. Fixture 和单元测试；
7. 低频灰度运行；
8. 健康度与采集质量评估；
9. 正式启用；
10. 建立降级和停用方案。

---

## 10. 核心数据模型

### 10.1 Source

```yaml
id: uuid
name: string
connector_type: string
platform: string
source_kind: feed | hotlist | account | board | search | manual
language: string
country: string
category: string
credibility_tier: S | A | B | C
config: jsonb
enabled: boolean
last_success_at: datetime
last_error: text
```

### 10.2 Signal

```yaml
id: uuid
source_id: uuid
platform: string
external_id: string
canonical_url: string
content_type: post | video | article | comment | statement
raw_title: text
raw_text: text
normalized_text: text
language: string
published_at: datetime
collected_at: datetime
metrics: jsonb
media: jsonb
content_hash: string
embedding: vector
embedding_provider: string
embedding_model: string
embedding_dimensions: integer
embedding_version: string
raw_payload_location: string
```

### 10.3 Event

```yaml
id: uuid
title: string
summary: text
category: string
status: emerging | growing | stable | declining | resolved
first_seen_at: datetime
last_updated_at: datetime
primary_language: string
entities: jsonb
keywords: jsonb
centroid_embedding: vector
source_count: integer
platform_count: integer
```

### 10.4 EventSignal

```yaml
event_id: uuid
signal_id: uuid
relation: origin | report | repost | reaction | official_response | correction
confidence: float
attached_by: rule | embedding | llm | human
```

### 10.5 EvidenceClaim

```yaml
id: uuid
event_id: uuid
claim_text: text
claim_type: fact | allegation | opinion | forecast
verification_state: confirmed | investigating | single_source | disputed | false
supporting_signal_ids: uuid[]
contradicting_signal_ids: uuid[]
editor_note: text
```

### 10.6 EditorialScore

```yaml
event_id: uuid
score_template: string
emotion: int
information_gap: int
visual_value: int
user_relevance: int
discussion: int
novelty: int
extendability: int
traffic_total: float
risk_level: R0 | R1 | R2 | R3 | R4
recommended_format: string
model_name: string
model_reason: text
human_override: jsonb
```

### 10.7 Draft、Publication、Performance

必须支持：

- 多稿件版本；
- 人工修改记录；
- 发布平台和 URL；
- 标题、封面文案、发布时间；
- 播放、完播、点赞、评论、分享和涨粉；
- 发布后 1 小时、24 小时、7 天数据；
- AI 推荐和人工采用的关联。

### 10.8 Checkpoint、账号、预算与风险事件

```text
connector_checkpoints
platform_accounts
account_risk_events
collection_budgets
signature_providers
```

关键要求：

- checkpoint 与连接器实例、账号、模式和查询条件绑定；
- 账号状态使用 `healthy/warning/cooldown/review_required/restricted/disabled`；
- 风险事件记录原始代码、系统动作和人工处理结果；
- 预算支持平台、账号、连接器和任务四种作用域；
- 签名实现可替换，主系统不直接引用平台 JS 文件。

---

## 11. 数据处理流水线

### 11.1 原始采集

- 采集器只负责获取和映射数据；
- 原始结果先保存；
- 写入幂等键；
- 保存游标、状态码、配额和失败原因；
- 不在采集器内部调用复杂 AI。

### 11.2 标准化

- 时间统一为 UTC；
- 界面按 Asia/Shanghai 展示；
- HTML 和模板清洗；
- 语言检测；
- URL 规范化；
- 互动指标统一；
- 提取 hashtag、mention、地点和实体候选。

### 11.3 低成本规则过滤

过滤：

- 空文本；
- 明显广告；
- 已知垃圾源；
- 重复链接；
- 无新增信息的旧搬运；
- 超出时间窗且没有再发酵价值的内容；
- 不必要的全部评论。

### 11.4 Embedding 与聚类

推荐顺序：

1. URL 和内容哈希；
2. 近似文本去重；
3. 云 Embedding 批处理；
4. 基于向量召回相似事件；
5. 结合时间、实体、地点和媒体哈希；
6. 高阈值自动合并；
7. 低阈值自动新建事件；
8. 边界样本交给 LLM；
9. 人工纠错进入评测集。

### 11.5 趋势计算

```text
velocity       = 最近时间窗口互动增量 / 时间
cross_source   = 独立来源数量
cross_platform = 平台数量
novelty        = 与历史事件的语义距离
cn_gap         = 海外信号强度 - 国内信号强度
update_value   = 新增事实 + 新增回应 + 新增画面
```

各平台互动指标必须先在平台内部归一化，不能直接拿微博点赞数与 Reddit upvote 比较。

### 11.6 证据抽取

模型只能对已有来源进行结构化提取：

```json
{
  "claims": [
    {
      "text": "监管工作人员称正在调查处置",
      "type": "fact",
      "state": "investigating",
      "supporting_signal_ids": ["signal-id"],
      "confidence": 0.88
    }
  ],
  "unknowns": ["尚无正式书面通报"]
}
```

没有 `supporting_signal_ids` 的内容不得进入“已确认事实”。

### 11.7 采集恢复与风险处理

```text
调度任务
→ 检查账号状态与预算
→ 读取 checkpoint
→ 执行低频采集
→ 分类响应与异常
→ 成功入库后推进 checkpoint
→ 风控信号则保存断点并熔断
```

错误分类：

- 可重试：网络超时、DNS、偶发 5xx、浏览器断连；
- 不可自动重试：验证码、403/406/429、权限拒绝、账号受限、`account blocked`、自动化/AI操作提示。

系统对不可重试风险不执行自动重新登录，不创建后续任务，并要求人工进入平台确认账号状态。

---

## 12. AI Gateway 与模型规划

### 12.1 任务路由

| 任务 | MVP 默认 | 后续选择 |
|---|---|---|
| Embedding | 云端低价 Embedding API | 本地Embedding、其他云厂商 |
| 事件抽取 | 低价云模型 | 本地小模型 |
| 边界聚类 | 低价云模型 | 更强模型复核 |
| 编辑评分 | 低价云模型 | 多模型投票 |
| 风险提取 | 低价云模型+规则 | 强模型复核 |
| TOP资料卡 | 低价云模型 | 强模型 |
| 深稿 | 强模型按需 | 本地大模型或人工 |
| 视觉分析 | 暂不全量启用 | 多模态模型 |
| ASR | 按候选事件调用 | 本地 Whisper Worker |

### 12.2 Provider 内部配置与导入导出示例

以下 YAML 代表数据库配置的序列化结果，日常配置由 AI Provider 中心完成：

```yaml
ai:
  providers:
    cloud_embedding:
      type: openai_compatible
      base_url: ${EMBEDDING_BASE_URL}
      credential_ref: secret://embedding/default

    low_cost_cloud:
      type: openai_compatible
      base_url: ${LOW_COST_LLM_BASE_URL}
      credential_ref: secret://llm/low-cost

    strong_cloud:
      type: openai_compatible
      base_url: ${STRONG_LLM_BASE_URL}
      credential_ref: secret://llm/strong

    local_ollama:
      type: openai_compatible
      base_url: http://localhost:11434/v1

  routes:
    embedding:
      primary: cloud_embedding
      fallbacks: [local_embedding]
    extraction:
      primary: low_cost_cloud
      fallbacks: [local_ollama]
    event_match:
      primary: low_cost_cloud
      fallbacks: [strong_cloud]
    scoring:
      primary: low_cost_cloud
      fallbacks: [strong_cloud]
    final_review:
      primary: strong_cloud
      fallbacks: [low_cost_cloud]
```

### 12.3 AI Provider 管理中心

Provider 页面提供：

- 新增、编辑、启用、停用和复制 Provider；
- 选择官方 OpenAI、OpenAI-compatible、本地 Ollama 或专用适配器；
- 设置 Base URL、超时、并发、重试、日预算和月预算；
- 录入/替换 API Key，页面只显示掩码；
- 测试网络、鉴权、模型调用、Embedding 和结构化输出；
- 同步或手工维护模型列表；
- 显示成功率、平均延迟、Token、费用和错误原因。

### 12.4 AI 任务路由中心

路由页面通过下拉框配置：

| 任务 | 主模型 | 备用模型链 | 失败策略 |
|---|---|---|---|
| Embedding | 云 Embedding | 本地 Embedding | 自动切换/暂停 |
| 事件抽取 | 低价云模型 | 本地小模型 | 重试后降级 |
| 事件匹配 | 低价云模型 | 强模型 | 边界样本人工处理 |
| 编辑评分 | 低价云模型 | 强模型 | 保留上次有效结果 |
| 证据整理 | 低价云模型 | 强模型 | 进入人工复核 |
| 稿件生成 | 低价云模型 | 强模型 | 重试/人工 |
| 最终复核 | 强模型 | 低价云模型 | 人工审核 |

每条路由还配置超时、重试次数、并发、预算超限策略和是否允许本地模型兜底。修改后仅影响新任务。

### 12.5 凭据和预算安全

- API Key、Cookie、OAuth Token 和代理密码与普通配置分表存储；
- 前端不可读取原始凭据，只能替换；
- 导出配置默认不包含敏感值；
- 配置日/月预算和告警阈值；
- 超预算时可以停止非必要任务、切换低价模型或切到本地模型；
- 所有 Provider、路由和预算修改进入审计日志。

### 12.6 成本控制

- 规则先过滤；
- Embedding 批处理；
- 同一内容不重复生成向量；
- 同一事件版本缓存 AI 结果；
- 评论先抽样再摘要；
- TOP20 才做深度分析；
- TOP5 才生成长稿；
- 强模型只处理 TOP1—TOP3；
- 设置日预算和月预算；
- 超预算时自动降级到低价模型或暂停非必要任务。

### 12.7 Prompt 与 Schema 管理

每次模型调用记录：

- prompt_version；
- schema_version；
- provider；
- model；
- temperature；
- input_hash；
- input_tokens；
- output_tokens；
- latency；
- cost；
- retry_count；
- human_feedback；
- 是否最终采用。

---

## 13. 编辑评分与风险模型

### 13.1 流量价值维度

| 维度 | 基础权重 |
|---|---:|
| 情绪张力 | 20 |
| 信息差 | 15 |
| 画面与素材 | 15 |
| 普通人相关度 | 15 |
| 讨论空间 | 15 |
| 新奇与反转 | 10 |
| 延展性 | 10 |

不同栏目采用不同权重模板。

### 13.2 风险等级

| 风险 | 定义 | 默认处理 |
|---|---|---|
| R0 | 多方权威确认 | 可直接进入候选 |
| R1 | 权威报道或官方调查中 | 明确标注调查状态 |
| R2 | 单一可信来源或完整原视频 | 观察或谨慎表达 |
| R3 | 截图、口述或搬运 | 不下结论 |
| R4 | 明显虚假、侵权或高法律风险 | 禁止发布 |

### 13.3 最终排序

```text
最终优先级
= 流量价值
× 栏目匹配度
× 时效系数
+ 信息增量
- 风险处罚
- 素材缺失处罚
```

规则分和 AI 语义分必须分别展示，避免完全黑箱。

---

## 14. 视频、图片和音频处理规划

### 14.1 分级处理

```text
全量信号：标题、文案、互动、链接
候选事件：字幕、简介、代表性评论
TOP20：无字幕时音频转写
TOP10：提取有限关键帧
TOP5：视觉分析和人工素材确认
```

### 14.2 长视频

- 优先官方字幕；
- 使用章节、评论高频时间点和标题定位；
- 音频分块转写；
- 分块摘要后汇总；
- 保留时间码；
- 不默认下载和永久保存完整视频。

### 14.3 媒体存储

默认保留：

- 原始 URL；
- 内容 ID；
- 字幕；
- 媒体哈希；
- 必要关键帧；
- 临时缓存文件；
- 自动过期时间。

---

## 15. 前端与用户流程规划

### 15.1 MVP 工作台

页面：

1. 今日概览；
2. 来源管理；
3. 连接器配置中心；
4. AI Provider 与任务路由中心；
5. 候选事件列表；
6. 事件详情；
7. 来源与时间线；
8. 评分与风险；
9. 合并与拆分；
10. 采用、观察、放弃、归档；
11. 稿件生成与编辑；
12. Markdown 导出；
13. API 成本日志；
14. 配置审计与导出；
15. 账号安全与风险控制中心；
16. checkpoint 查看、继续运行和人工重置。

MVP 的配置中心先实现高频操作：列表、表单编辑、启停、测试连接、立即运行、模型路由、凭据替换和基础日志。扫码/OAuth 专属流程按平台阶段加入。

### 15.2 V1 工作台

增加：

- Schema 自动表单和平台专属配置组件；
- 连接器批量启停、配置复制、版本差异和回滚；
- 连接器健康状态、配额、凭据过期和多节点状态；
- 账号状态机、风险事件时间线、冷却和人工恢复；
- 平台/账号/任务三级预算与试运行模式；
- HomeFeed 白名单与单次条数限制；
- Provider 模型同步、降级链、预算告警和费用趋势；
- 事件生命周期；
- 评论情绪摘要；
- 素材关键帧；
- 稿件版本对比；
- Prompt 和模型结果历史；
- 来源命中率；
- CSV 发布数据导入。

### 15.3 V1.5 / V2 工作台

增加：

- 多人协作；
- 权限和审批；
- 选题日历；
- 栏目模板；
- 可视化数据看板；
- 错题集和模型评测；
- 用户投稿审核；
- 发布接口或导出到剪辑工作流。

---

## 16. API 规划

```text
# 连接器定义与可视化配置
GET    /api/connector-definitions
GET    /api/connector-definitions/{type}/schema
POST   /api/connector-instances
GET    /api/connector-instances
PUT    /api/connector-instances/{id}
POST   /api/connector-instances/{id}/enable
POST   /api/connector-instances/{id}/disable
POST   /api/connector-instances/{id}/test
POST   /api/connector-instances/{id}/run
GET    /api/connector-instances/{id}/health
GET    /api/connector-instances/{id}/runs
GET    /api/connector-instances/{id}/checkpoint
POST   /api/connector-instances/{id}/resume
POST   /api/connector-instances/{id}/reset-checkpoint
GET    /api/connector-instances/{id}/versions
POST   /api/connector-instances/{id}/rollback

# 平台账号、预算与风险控制
GET    /api/platform-accounts
POST   /api/platform-accounts
PUT    /api/platform-accounts/{id}
POST   /api/platform-accounts/{id}/test
POST   /api/platform-accounts/{id}/pause
POST   /api/platform-accounts/{id}/resume
GET    /api/platform-accounts/{id}/risk-events
GET    /api/risk-policies
PUT    /api/risk-policies/{id}
GET    /api/collection-budgets
PUT    /api/collection-budgets/{scope_type}/{scope_id}

# AI Provider与任务路由
POST   /api/ai/providers
GET    /api/ai/providers
PUT    /api/ai/providers/{id}
POST   /api/ai/providers/{id}/test
POST   /api/ai/providers/{id}/sync-models
GET    /api/ai/models
GET    /api/ai/routes
PUT    /api/ai/routes/{task_type}
GET    /api/ai/usage

# 配置导入导出与审计
POST   /api/config/import/preview
POST   /api/config/import/apply
GET    /api/config/export
GET    /api/config/audit-logs

# 来源
POST   /api/sources
GET    /api/sources
PUT    /api/sources/{id}

# 信号
GET    /api/signals
GET    /api/signals/{id}
POST   /api/signals/import-url
POST   /api/signals/import-file

# 事件
GET    /api/events
GET    /api/events/{id}
POST   /api/events/{id}/merge
POST   /api/events/{id}/split
POST   /api/events/{id}/rescore
POST   /api/events/{id}/status
POST   /api/events/{id}/refresh

# 编辑
GET    /api/editorial/daily
POST   /api/editorial/generate
POST   /api/editorial/{event_id}/decision
PUT    /api/editorial/{event_id}/score

# 稿件
GET    /api/drafts/{event_id}
POST   /api/drafts/{event_id}/generate
PUT    /api/drafts/{draft_id}
GET    /api/drafts/{draft_id}/versions
GET    /api/drafts/{draft_id}/export.md

# 发布和复盘
POST   /api/publications
POST   /api/performance/import
GET    /api/analytics/sources
GET    /api/analytics/editorial
GET    /api/analytics/costs
GET    /api/analytics/missed-events
```

---

## 17. Windows 与 Docker 部署基线

### 17.1 推荐结构

```text
Windows 11
├── 本地 MySQL              3306
├── 本地 SQL Server         1433
├── Docker Desktop / WSL2
│   ├── PostgreSQL+pgvector 宿主55432 -> 容器5432
│   ├── 后续 Redis          宿主56379 -> 容器6379
│   └── 后续 MinIO          自定义端口
├── MediaCrawler + Chrome 登录态
├── FastAPI / Worker
└── 云 AI API
```

### 17.2 Docker Compose 基线

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: ai_editorial
      POSTGRES_USER: ai_editorial
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "127.0.0.1:55432:5432"
    volumes:
      - ai_editorial_pgdata:/var/lib/postgresql/data

volumes:
  ai_editorial_pgdata:
```

### 17.3 连接字符串

```env
DATABASE_URL=postgresql+asyncpg://ai_editorial:${POSTGRES_PASSWORD}@localhost:55432/ai_editorial
```

---

# 18. 分阶段开发总计划

本项目采用“完整规划、分批交付、每批可验收”的方式。后续阶段已全部纳入路线图，不在第一批完成不代表被忽略。

---

## 阶段 M0：项目启动与规则冻结

### 目标

建立可开发的统一基线，避免边写边改核心定义。

### 主要工作

- 建立 Git 仓库；
- 确定目录结构；
- 创建环境配置规范；
- 确定事件、信号、来源和证据定义；
- 确定栏目和评分模板；
- 准备 30—50 个历史事件评测样本；
- 确定首批来源清单和测试账号；
- 建立开发、测试和生产配置分离；
- 冻结连接器 Definition、JSON Schema、敏感字段和配置版本规则；
- 冻结 AI 任务类型、Provider 能力和路由模型；
- 冻结 MediaCrawler 五项增强边界；
- 冻结风险错误分类、账号状态机和不可绕过的安全约束。

### 交付物

- 仓库骨架；
- `.env.example`；
- 开发规范；
- 数据模型初稿；
- 评分配置；
- 历史评测集；
- Docker Compose 基础文件。

### 验收标准

- 新开发者可以启动空项目；
- 数据库可创建；
- 评分维度有明确解释；
- 历史事件样本包含同事件、不同事件和跨语言样本。

### 预计时间

2—3 个有效开发日。

---

## 阶段 M1：基础设施、统一数据结构与连接器框架

### 目标

搭建所有后续平台和 AI 能力共同依赖的底座。

### 主要工作

- FastAPI 主服务；
- PostgreSQL + pgvector；
- SQLAlchemy 模型和迁移；
- Connector SDK；
- Connector Definition Registry；
- JSON Schema / UI Schema；
- 连接器实例配置 API；
- 基础可视化连接器中心：列表、新建、编辑、启停、测试、立即运行；
- 配置版本和审计日志；
- Scheduler；
- Raw Signal 入库；
- 健康检查和任务日志；
- 手工 URL 导入；
- RSS 连接器；
- 基础热榜连接器框架；
- checkpoint 与增量水位基础设施；
- PlatformRiskGuard、错误分类和单平台熔断；
- 平台/账号/任务三级预算；
- platform_accounts、account_risk_events 和 collection_budgets 数据表。

### 平台状态

- RSS：实现并启用；
- 手工 URL：实现并启用；
- 国内热榜：至少一个入口实现；
- MediaCrawler 七个平台：完成注册定义，但尚未全部启用。

### 交付物

- 可运行后端；
- 数据库迁移；
- 连接器示例；
- 连接器配置中心基础页面；
- Schema 动态表单基础组件；
- 原始信号列表 API；
- 任务日志；
- checkpoint 调试页或 API；
- 账号风险日志和暂停/恢复 API；
- 本地启动说明。

### 验收标准

- 任一连接器都能输出统一 RawSignal；
- 重复任务不会重复写入；
- 单一连接器失败不影响其他连接器；
- 能从 RSS 和手工 URL 生成信号；
- 不修改 YAML 即可新增、编辑、启停和测试连接器；
- 无效配置不能覆盖上一有效版本；
- 明确风控错误不会进入普通重试循环；
- 账号达到预算或触发限制后，后续任务会被阻止。

### 预计时间

5—8 个有效开发日。

---

## 阶段 M2：MediaCrawler 全平台注册与首批国内平台启用

### 目标

将 MediaCrawler 当前支持的七个平台全部纳入主系统，并验证第一批平台。

### 主要工作

- MediaCrawler Adapter；
- CLI 子进程或结果文件接入；
- 七个平台字段映射；
- 平台能力声明；
- Cookie、扫码登录和登录状态的可视化配置；
- MediaCrawler 七个平台专属 Schema；
- 采集任务状态同步；
- 评论抽样接口；
- 失败日志和恢复；
- 断点续采与增量采集接入；
- 账号、浏览器 Profile 和可选固定代理抽象；
- SignatureProvider 接口与现有签名实现适配；
- 新账号连通性测试与低量试运行；
- 微博、B站、知乎启用并实跑。

### 平台状态

| 平台 | 本阶段状态 |
|---|---|
| 微博 | 实现、启用、验证 |
| B站 | 实现、启用、验证 |
| 知乎 | 实现、启用、验证 |
| 抖音 | 实现、默认关闭 |
| 小红书 | 实现、默认关闭 |
| 快手 | 实现、默认关闭 |
| 百度贴吧 | 实现、默认关闭 |

### 交付物

- MediaCrawler Adapter；
- 七个平台配置模板；
- 微博/B站/知乎测试报告；
- 登录失效提示；
- 七个平台配置表单；
- 平台字段映射文档；
- 五项 MediaCrawler 增强实现说明；
- 首批平台账号安全测试报告。

### 验收标准

- 七个平台均可在注册中心显示；
- 三个首启平台可以独立运行；
- 关闭某个平台不影响其他平台；
- 信号均保留原始 URL、平台 ID 和采集时间；
- 七个平台可以在后台分别启停和调整采集参数；
- Cookie/登录态不可从前端明文读取；
- 任务中断可从断点继续；
- 重复内容不重复请求或入库；
- 权限拒绝、验证码和账号受限会触发暂停并进入人工检查。

### 预计时间

5—9 个有效开发日，视平台适配、断点方式和登录变化而定。

---

## 阶段 M3：Embedding、去重与事件聚类

### 目标

从“帖子数据库”升级为“事件数据库”。

### 主要工作

- 文本规范化；
- URL 和哈希去重；
- 近似文本去重；
- 云 Embedding Provider；
- Provider 基础管理、测试连接和模型记录；
- Embedding 任务路由与本地备用接口；
- Embedding 批处理与缓存；
- pgvector 相似检索；
- 事件创建和信号挂载；
- 自动合并阈值；
- LLM 边界判断；
- 人工合并和拆分；
- 聚类评测工具。

### 交付物

- Event、EventSignal 表；
- 聚类 Worker；
- 合并/拆分 API；
- 聚类评测集；
- Embedding 成本统计；
- Embedding Provider 配置页面。

### 验收标准

- 相同链接不重复入库；
- 同一事件不同平台内容大部分可正确合并；
- 相似但不同事件不能大量误合并；
- 人工纠错可以保存；
- 更换 Embedding Provider 时可按版本重建；
- 页面可以切换主/备用 Embedding 模型并完成连接测试。

### 预计时间

4—7 个有效开发日。

---

## 阶段 M4：AI 编辑评分、证据和资料卡

### 目标

让系统能够判断“哪些事件值得讲”，并提供可核验的编辑资料。

### 主要工作

- AI Gateway；
- OpenAI 兼容 Provider；
- AI Provider 可视化管理；
- 模型同步、能力标注和连接测试；
- 任务路由、备用链、预算和失败策略；
- Prompt 版本管理；
- JSON Schema 输出；
- 事件要素抽取；
- 来源和证据状态抽取；
- 流量价值评分；
- 风险等级；
- 栏目适配；
- 推荐时长；
- TOP20 / TOP10 / TOP5；
- 事件资料卡；
- 30 秒和 2—3 分钟稿件；
- 调用成本和失败重试。

### 交付物

- AI Gateway；
- Provider 与任务路由配置页面；
- Prompt 模板；
- EditorialScore；
- EvidenceClaim；
- 每日 TOP 列表；
- Markdown 事件资料卡。

### 验收标准

- 所有模型结果符合 Schema；
- 已确认事实都有来源 ID；
- 风险分和流量分独立展示；
- 每个评分维度有理由；
- 资料卡可直接供人工编辑；
- API 成本可追踪；
- Provider、模型和路由均可在后台修改，无需改业务代码；
- 预算超限和 Provider 故障可按配置降级。

### 预计时间

4—7 个有效开发日。

---

## 阶段 M5：MVP 编辑工作台与两周闭环

### 目标

形成每天可实际使用的最小编辑工作台。

### 主要工作

- 今日概览；
- 候选事件列表；
- 事件详情；
- 来源链和时间线；
- 评分和风险；
- 合并/拆分；
- 采用/观察/放弃/归档；
- 稿件编辑；
- Markdown 导出；
- 来源健康状态；
- 账号安全、风险事件、预算与人工恢复；
- checkpoint 查看、继续运行和重置；
- 连接器和 Provider 配置中心整合；
- 配置导入导出、修改历史和基础回滚；
- 每日调度；
- 一周连续实跑。

### 每日默认流程

```text
08:00—12:00 发现早期信号
12:00—17:00 增量采集和事件补全
18:00        候选池收口与重新评分
18:30        生成 TOP10 和 TOP3 资料包
人工审核后   输出脚本和素材清单
```

### 交付物

- Web 工作台；
- 日报；
- TOP10；
- TOP3 完整资料包；
- 使用日志；
- 配置审计日志；
- 一周实跑报告。

### 验收标准

- 每天稳定采集至少五类来源；
- 每个事件可追溯到原始链接；
- 人工能在工作台完成选题闭环；
- 生成稿不把调查中写成已定案；
- 一周内能统计推荐采用率和平均成本；
- 日常调整平台、频率、账号、模型和路由不需要直接编辑 YAML；
- 导入错误配置不会破坏当前运行配置；
- 高风险平台触发限制时不会持续请求；
- 账号风险与普通采集错误在工作台中分开显示。

### 预计时间

3—5 个有效开发日，加 5—7 天实跑观察。

---

## 阶段 V1-A：启用抖音、小红书、快手和贴吧

### 目标

扩大国内短视频、生活方式和兴趣社区的发现面。

### 主要工作

- 启用抖音连接器；
- 启用小红书连接器；
- 启用快手连接器；
- 启用贴吧连接器；
- 账号与关键词配置；
- 评论抽样；
- 频率和风控控制；
- 账号状态机、风险策略模板和熔断；
- 候选事件补全模式；
- 少量 HomeFeed 白名单灰度；
- checkpoint 和增量效果统计；
- 平台内热度归一化；
- 来源质量和命中率统计；
- 平台专属动态表单、批量启停、配置复制和版本回滚；
- 多账号登录态和凭据过期提醒。

### 重点注意

- 不默认全量抓评论；
- 使用独立测试账号；
- 逐个平台灰度开启；
- 页面变化时允许快速停用；
- 不让平台故障拖垮主流程；
- 不将小红书或抖音设为全量高频发现入口；
- 不自动换号、换代理或反复扫码绕过限制；
- 风控提示只能人工确认后恢复。

### 验收标准

- 四个平台可分别启停；
- 连续运行一周成功率达到可接受水平；
- 每个平台能贡献有效候选事件；
- 风控失败有明确日志和恢复路径；
- 四个平台的配置可在后台完成并保留历史版本；
- 风控信号触发后能在一次任务内完成停止和熔断；
- HomeFeed 可单独停用，不影响账号监控、详情和关键词补全。

### 预计时间

2—4 周，按平台逐一推进。

---

## 阶段 V1-B：事件生命周期、趋势和信息差增强

### 目标

从“每日静态候选”升级为“持续跟踪事件”。

### 主要工作

- 事件状态：emerging、growing、stable、declining、resolved；
- 事件跨天更新；
- 新增事实和新增画面检测；
- 海外/国内信息差指数；
- 平台内互动增速归一化；
- 旧事件重新发酵识别；
- 官方回应和更正自动关联；
- 时间线自动生成。

### 验收标准

- 同一事件跨天不重复新建；
- 新增官方回应可挂到既有事件；
- 能区分旧闻搬运和真正的新进展；
- 能展示事件趋势变化原因。

### 预计时间

2—3 周。

---

## 阶段 V1-C：视频字幕、ASR、关键帧和 OCR

### 目标

让系统从文本理解扩展到有限度的多媒体理解。

### 主要工作

- 字幕优先获取；
- 无字幕候选视频音频转写；
- 长音频分块；
- 关键帧抽取；
- 图片和截图 OCR；
- 视觉模型分析；
- 时间码与事实关联；
- 临时缓存自动清理。

### 范围控制

- 不处理所有视频；
- TOP20 才转写；
- TOP10 才抽帧；
- TOP5 才做视觉模型分析；
- 不默认永久存完整视频。

### 验收标准

- 字幕和转写保留时间码；
- 转写失败不影响文本流程；
- 媒体缓存可自动过期；
- 视觉结论不得脱离来源画面。

### 预计时间

2—4 周。

---

## 阶段 V1-D：复盘、数据回流和评分校准

### 目标

让系统根据真实账号表现持续学习，而不是永远依赖初始权重。

### 主要工作

- 手工和 CSV 导入发布数据；
- 记录标题、栏目、时长和发布时间；
- 统计来源命中率；
- AI 推荐采用率；
- 被放弃后爆发事件；
- 播放和互动相关性；
- 栏目权重调整；
- Prompt A/B 测试；
- 错题集。

### 验收标准

- 可计算每个被采用选题的 AI 成本；
- 可比较系统 TOP10 与人工 TOP10；
- 可识别高命中来源和低价值来源；
- 每月可生成评分校准建议。

### 预计时间

2—3 周建立基础能力，后续持续迭代。

---

## 阶段 V1.5-A：YouTube 与海外地方新闻

### 目标

增强海外长视频、Shorts 和地方奇闻发现。

### 主要工作

- YouTube Data API；
- 频道和播放列表监控；
- 搜索配额预算；
- 视频字幕和章节；
- 海外地方新闻 RSS 模板；
- 国家、地区和语言标签；
- 跨语言聚类评测。

### 验收标准

- 频道监控稳定；
- 配额消耗可查看；
- 英文事件可与中文搬运内容合并；
- 海外来源能生成国内信息差指标。

### 预计时间

2—4 周。

---

## 阶段 V1.5-B：X、Instagram 和 TikTok

### 目标

建立海外记者、明星、视觉文化和短视频线索能力。

### X 规划

- 账号列表监控；
- 有限关键词查询；
- 记者、媒体和科技账号分类；
- 套餐和配额可配置；
- API 不可用时降级到其他来源。

### Instagram / IG 规划

- 授权账号接入；
- 指定专业账号监控；
- 手工 URL 导入；
- 不假设官方 API 能进行全站热门搜索；
- 海外发现先由 Reddit、X、新闻或其他来源触发，IG 用于素材补全。

### TikTok 规划

- 独立于抖音的连接器；
- 账号和授权内容优先；
- 研究接口不作为默认商业依赖；
- 先完成手工 URL 和账号监控，再评估趋势发现。

### 验收标准

- 三个平台均有独立能力声明；
- 不依赖任何一个不稳定接口维持主流程；
- 连接器可随时禁用；
- 账号和授权范围清晰可审计；
- OAuth 授权、Token 过期和账号范围在可视化配置中心管理。

### 预计时间

4—8 周，取决于可用 API、账号权限和配额。

---

## 阶段 V2-A：高级 AI 编辑与多模型协作

### 目标

提高复杂事件判断、稿件质量和可解释性。

### 主要工作

- 多模型路由；
- 边界聚类模型投票；
- 强模型最终复核；
- 多栏目独立 Prompt；
- 事实冲突检测；
- 观点光谱；
- 风险表达模板；
- 稿件风格模板；
- 账号语气记忆；
- 标题和开场 A/B 候选。

### 验收标准

- 复杂事件误合并率下降；
- 争议事件能并列展示冲突来源；
- 稿件事实错误率可通过评测追踪；
- 人工修改比例逐步下降但不取消审核。

### 预计时间

3—6 周，并持续优化。

---

## 阶段 V2-B：知识库、搜索和历史事件复用

### 目标

让历史内容、人物、行业和旧事件成为可检索资产。

### 主要工作

- 全文搜索；
- 向量搜索；
- 人物和机构实体页；
- 相关历史事件；
- 同类选题模板；
- 已发布稿件检索；
- 重复选题提醒；
- 旧事件重新发酵对比。

### 验收标准

- 编辑可检索历史事件和稿件；
- 新事件可自动关联相关历史背景；
- 系统能提醒“已做过类似内容”；
- 历史资料引用仍保留原始来源。

### 预计时间

3—5 周。

---

## 阶段 V2-C：团队协作与运营工作流

### 目标

从个人工具升级为小团队编辑系统。

### 主要工作

- 用户和角色；
- 主编、编辑、审核权限；
- 连接器、Provider、预算和高风险配置的审批流程；
- 配置变更审计和回滚权限；
- 任务分配；
- 评论和批注；
- 稿件审批；
- 选题日历；
- 操作审计；
- 数据权限；
- 多账号或多栏目配置。

### 验收标准

- 不同角色权限隔离；
- 稿件修改有历史；
- 操作可审计；
- 多人同时编辑不覆盖数据。

### 预计时间

3—6 周。

---

## 阶段 V2-D：投稿、浏览器插件与外部线索入口

### 目标

让用户和编辑团队主动提交线索，补充算法发现。

### 主要工作

- 投稿表单；
- 邮件转线索；
- 浏览器收藏插件；
- URL 一键入库；
- 文件和截图导入；
- 恶意链接和文件检查；
- 投稿审核队列；
- 来源贡献统计。

### 验收标准

- 投稿不会直接进入已确认事件；
- 外部文件经过安全检查；
- 投稿来源可追踪；
- 重复投稿可自动合并。

### 预计时间

2—4 周。

---

## 阶段 P1：稳定运行、性能和可观测性

### 目标

从“能用”升级为“可长期运行”。

### 主要工作

- Redis 和任务队列；
- Worker 并发；
- 任务优先级；
- 超时和重试策略；
- 连接器熔断；
- 指标和告警；
- 成本告警；
- 数据备份；
- 媒体对象存储；
- 数据保留和删除；
- 灾难恢复演练。

### 验收标准

- 单平台故障不影响日报；
- 任务可重试且不会重复写入；
- 数据库有自动备份；
- 成本、磁盘和失败率有告警；
- 连续运行 30 天没有重大数据丢失。

### 预计时间

4—8 周，并持续维护。

---

## 阶段 P2：未来发布与外部系统集成

### 目标

在合规和稳定前提下，将系统与剪辑、发布或运营工具连接。

### 可选能力

- 导出剪辑脚本；
- 导出字幕文件；
- 导出素材时间码；
- 与项目管理工具同步；
- 发布日历；
- 平台草稿接口；
- 发布数据自动回流；
- Webhook 通知。

### 原则

- 自动发布不是系统核心；
- 所有发布必须保留人工确认；
- 不为了自动化牺牲平台安全；
- 平台接口变化时可关闭发布功能，不影响编辑主流程。

---

## 19. 各阶段依赖关系

```text
M0 规则冻结
↓
M1 基础设施与连接器框架
↓
M2 MediaCrawler 全平台注册与首批启用
↓
M3 去重、Embedding、事件聚类
↓
M4 AI评分、证据、资料卡
↓
M5 MVP工作台与实跑
├─ V1-A 国内平台全面启用
├─ V1-B 生命周期与趋势
├─ V1-C 多媒体处理
└─ V1-D 数据回流
     ↓
V1.5 海外平台
     ↓
V2 高级AI、知识库、团队协作、投稿
     ↓
P1 稳定运行与扩容
     ↓
P2 发布和外部系统集成
```

V1 的四条支线可以部分并行，但必须在 MVP 主闭环稳定后开始。

---

## 20. 版本交付定义

### MVP 完成定义

- 至少五类来源稳定采集；
- MediaCrawler 七个平台已注册，微博/B站/知乎已启用；
- RSS、Reddit、热榜和手工 URL 可用；
- 信号可去重和聚类成事件；
- 有 TOP10 和 TOP3 资料卡；
- 有流量分、风险分和来源链；
- 有 30 秒和 2—3 分钟稿；
- 有人工采用、观察和放弃；
- 有 Markdown 导出；
- 有 AI 成本日志；
- 连续实跑一周。

### V1 完成定义

- MediaCrawler 七个平台可逐一启用并经过验证；
- 事件生命周期可跨天追踪；
- 评论抽样和趋势计算可用；
- 有字幕/ASR/关键帧的分级处理；
- 有发布数据手工或 CSV 回流；
- 有来源命中率和错题集；
- 连续运行一个月。

### V1.5 完成定义

- YouTube、X、IG、TikTok 至少按其可用能力接入；
- 海外地方新闻源形成配置库；
- 跨语言聚类达到可接受准确度；
- 海外到国内的信息差链路可用。

### V2 完成定义

- 高级模型路由；
- 知识库和历史检索；
- 团队权限和审批；
- 投稿和外部线索入口；
- 完整复盘和数据看板。

---

## 21. 测试与评测计划

### 21.1 单元测试

- URL 规范化；
- 时间转换；
- 内容哈希；
- 指标映射；
- 评分公式；
- Schema 校验；
- Provider 降级；
- 成本计算。

### 21.2 连接器测试

- 使用合法响应 Fixture；
- CI 中不进行大规模真实请求；
- 每个平台维护 smoke test；
- 页面结构变化时快速定位；
- 登录失效和配额耗尽有测试。

### 21.3 聚类评测

样本必须包含：

- 同一事件不同说法；
- 中英文同一事件；
- 相似但不同事件；
- 同一人物不同事件；
- 旧闻重新发酵；
- 搬运、评论和官方回应。

指标：

- Precision；
- Recall；
- 误合并率；
- 漏合并率；
- 人工纠错率。

### 21.4 编辑评测

每周比较：

- 系统 TOP10；
- 人工 TOP10；
- 实际发布内容；
- 实际高流量内容；
- 系统放弃但后来爆发的事件；
- 稿件人工修改比例；
- 每个采用事件的 AI 成本。

---

## 22. 安全、合规和版权注意事项

1. 不绕过验证码、付费墙、权限控制或平台安全措施；
2. 不使用正式运营账号进行高风险采集测试；
3. Cookie、Token 和 API Key 不写入代码仓库；
4. 原始视频原则上只保存链接、字幕、哈希和必要关键帧；
5. 不将单一网友评论写成事实；
6. 涉及食品、灾害、医疗、法律、金融和政治等高风险事件时提高证据门槛；
7. 传闻必须标记为传闻；
8. AI 不得生成不存在的官方回应、采访或截图；
9. 第三方 AI API 不上传账号凭据和不必要的隐私数据；
10. 每个平台单独维护条款、配额和数据删除要求；
11. 项目用途发生变化时重新评估 MediaCrawler 和平台许可；
12. 用户投稿必须经过恶意文件和链接检查；
13. 国内平台采集使用独立测试账号和独立浏览器 Profile，不与正式发布账号共用；
14. 对验证码、权限拒绝、账号受限和自动化检测执行停止、熔断与人工复核；
15. 不开发验证码破解、指纹伪造、受限后自动换号或代理轮换绕过限制的功能；
16. HomeFeed、评论和媒体下载采用低频、少量、可随时停用的灰度策略；
17. 风险保护只能降低概率，不能对账号安全作绝对保证。

---

## 23. 可观测性与运营指标

### 23.1 连接器指标

- 请求数；
- 新信号数；
- 失败数；
- 成功率；
- 重试数；
- 平均耗时；
- 配额余额；
- 登录健康状态；
- checkpoint 恢复成功率；
- 增量采集避免的重复请求；
- 风控事件数、熔断率与人工恢复时长。

### 23.2 事件指标

- 聚类前后压缩比；
- 每日新增事件；
- 跨平台事件比例；
- 人工合并和拆分率；
- 事件平均来源数；
- 事件从首次发现到采用的时间。

### 23.3 编辑指标

- AI 推荐采用率；
- TOP10 与人工选择重合率；
- 稿件人工修改比例；
- 放弃后爆发率；
- 每个采用事件成本；
- 每个来源的首发命中率；
- 每日出稿耗时。

### 23.4 系统告警

- 连接器连续失败；
- 登录失效；
- 配额耗尽；
- 采集量异常为零；
- 数据库不可用；
- 磁盘空间不足；
- AI 成本超预算；
- Worker 堆积；
- 事件聚类异常暴增或暴跌；
- 账号进入 review_required/restricted；
- 验证码、权限拒绝、403/406/429、account blocked；
- 单账号达到日预算；
- 同一平台短时间连续风控事件。

---

## 24. 风险清单与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| 平台页面变化 | 采集失败 | 连接器隔离、Fixture、快速禁用 |
| 登录风控或账号封禁 | 账号受限、数据中断 | 独立测试账号、固定Profile、低量试跑、预算、不可重试错误、自动熔断与人工恢复 |
| API价格变化 | 成本上升 | Provider路由、预算上限、本地备用 |
| Embedding模型更换 | 向量不兼容 | 模型版本化、全量重建脚本 |
| 事件误合并 | 事实混乱 | 阈值分层、LLM边界判断、人工拆分 |
| 事件漏合并 | 候选重复 | 多特征召回、跨语言评测 |
| AI幻觉 | 稿件错误 | 来源ID约束、Schema、人工审核 |
| 视频存储膨胀 | 磁盘不足 | 分级处理、缓存过期、不全量下载 |
| 功能范围失控 | 工期延误 | 分阶段验收、阶段外需求进Backlog |
| 单平台依赖 | 系统脆弱 | 多来源、可插拔连接器、降级 |
| 普通重试放大风控 | 账号风险升级 | 风控错误分类、禁止自动重登、保存断点后立即暂停 |
| HomeFeed形成新信息茧房 | 发现偏差 | 仅作补充，结合热榜、RSS、Reddit和账号监控 |
| checkpoint错误推进 | 漏数据 | 成功入库后再推进、支持人工重置和审计 |

---

## 25. 开发协作方式

### 25.1 开发过程

每一阶段采用：

1. 确认阶段目标；
2. 拆分任务；
3. 完成代码和测试；
4. 本地运行；
5. 提交日志和结果；
6. 修复问题；
7. 验收；
8. 进入下一阶段。

### 25.2 用户侧需要配合

- Windows 本地运行；
- Docker Desktop 安装；
- 国内平台扫码登录；
- 提供独立测试账号；
- 配置云 AI API Key；
- 提供报错日志；
- 对系统推荐事件进行人工反馈；
- 录入发布后的实际数据。

### 25.3 代码交付要求

每一阶段都应包含：

- 可运行代码；
- 数据库迁移；
- `.env.example`；
- 配置示例；
- 测试；
- 启动说明；
- 已知问题；
- 验收清单；
- 下一阶段依赖。

---

## 26. 当前建议执行顺序

准备开始开发时，建议依次执行：

1. M0：规则冻结和仓库初始化；
2. M1：PostgreSQL、FastAPI、连接器框架、RSS、热榜、checkpoint和风险保护底座；
3. M2：MediaCrawler七平台注册，完成五项增强中的基础部分，启用微博/B站/知乎并低量验证；
4. M3：云Embedding、去重和事件聚类；
5. M4：AI评分、证据和资料卡；
6. M5：工作台和一周实跑；
7. 根据实跑结果进入 V1-A，对抖音/小红书/快手/贴吧逐个平台灰度，并评估少量HomeFeed；
8. 并行推进 V1-B、V1-C、V1-D；
9. 国内链路稳定后接海外平台；
10. 最后增加高级AI、知识库、团队协作和稳定性扩容。

---

## 27. 当前开发基线结论

本项目不是“在 MediaCrawler 上增加几个平台和 AI 接口”这么简单，而是一套完整的事件编辑系统。MediaCrawler 是国内平台采集能力的重要组成部分，但核心资产是：

- 统一信号模型；
- 可插拔连接器；
- 跨平台事件聚类；
- 证据与事实链；
- 编辑评分；
- 稿件与人工审核；
- 发布数据回流；
- 可持续复盘的知识库；
- 可恢复的增量采集运行时；
- 平台账号风险保护和人工可控的熔断机制。

开发应从可验证的最小闭环开始，但完整路线必须始终保留。本文档已经将第一批、后续国内平台、海外平台、多媒体、复盘、高级 AI、知识库、团队协作和稳定运行分别列出，可作为整个项目的长期开发总纲。

---

## 28. 本次增强参考

- MediaCrawler 项目与 Pro 功能说明：<https://github.com/NanmiCoder/MediaCrawler>
- 小红书账号永久封禁反馈：<https://github.com/NanmiCoder/MediaCrawler/issues/865>
- 小红书检测到 AI 操作反馈：<https://github.com/NanmiCoder/MediaCrawler/issues/915>
- 小红书权限拒绝与重复重试日志：<https://github.com/NanmiCoder/MediaCrawler/issues/906>

上述 Issue 仅用于识别风险场景和设计保护措施，不代表任何单一配置能够保证账号安全。
