# MediaCrawler 本地集成变更记录

## 当前上游基线

- Vendored 路径：`third_party/MediaCrawler/`
- 上游仓库：`NanmiCoder/MediaCrawler`
- 固定上游 commit：`071c8c0acaece3e82f2532cffb19faeddc9ec1c3`
- 引入方式：vendored subtree / squash import
- 许可证：`NON-COMMERCIAL LEARNING LICENSE 1.1`

M2-A 不更新上游版本，不改变许可证，不移除上游 LICENSE 或来源记录。任何使用仍需遵守该非商业学习许可证和目标平台规则。

## M2-A 边界

M2-A 只建立主系统与 vendored MediaCrawler 之间的正式集成层：

```text
CollectionTask
→ CollectorRuntime
→ MediaCrawlerConnector
→ MediaCrawlerAdapter
→ MediaCrawlerSubprocessRunner
→ third_party/MediaCrawler
→ JSONL / Result Envelope
→ CollectionResult / RawSignal
```

主系统继续拥有并负责：

- Connector Implementation Registry；
- Run 生命周期与原子领取；
- Collection Budget；
- Risk Guard 与平台风险处置；
- `connector_checkpoints`；
- RawSignal 标准化、幂等与数据库事务；
- 日志、审计和运营状态。

MediaCrawler 只作为第三方采集执行体。它不拥有主系统 ORM、AsyncSession、DATABASE_URL、Admin Token、Run、Checkpoint 或 RawSignal 事务。

## Versioned Invocation Protocol

M2-A 新增 `MediaCrawlerInvocation`，当前版本：

```text
protocol_version = "1.0"
```

字段包括：

- `protocol_version`
- `run_id`
- `platform`
- `mode`
- `source_id`
- `keyword`
- `creator_id`
- `content_ids`
- `requested_limit`
- `comment_limit`
- `include_comments`
- `include_subcomments`
- `checkpoint`
- `account_ref`
- `browser_profile_ref`
- `timeout_seconds`

协议使用 Pydantic v2 Domain Model，支持 JSON 序列化并拒绝未知字段。Invocation 不传 ORM、数据库 Session、DATABASE_URL、Admin Token、明文 Cookie、明文 Token 或 Authorization。

`account_ref` 与 `browser_profile_ref` 只是不透明引用。M2-A runner 不用这些引用实现真实登录；账号/Profile 真实接入属于后续 M2-C。

## Versioned Result Envelope

M2-A 新增 `MediaCrawlerResultEnvelope`，包含：

- `protocol_version`
- `run_id`
- `platform`
- `status`
- `items`
- `comments`
- `checkpoint`
- `counters`
- `warnings`
- `risk_events`
- `errors`
- `started_at`
- `finished_at`

stdout/stderr 不再作为业务结果协议。它们只用于受大小限制的诊断与错误分类。

当前 vendored MediaCrawler 本身支持 JSONL 文件输出，因此 M2-A runner 将 `--save_data_path` 固定到主系统为单个 Run 创建的安全临时目录，采集结束后读取该目录内 JSONL，再生成并重新校验 Result Envelope。

M2-A 不实现七个平台完整字段 Mapper。Result Envelope 中的标准 item 进入 RawSignal 所需的最小公共形状仅包含稳定 `external_id`、`url` 及可选公共字段；各平台真实字段映射属于 M2-B。

## 临时目录与结果安全

`MediaCrawlerSubprocessRunner`：

- 每个 Run 使用独立 `TemporaryDirectory`；
- 结果根目录由主系统创建，third-party 不能从 Invocation 指定任意结果路径；
- 仅遍历受控根目录内 JSONL；
- 拒绝结果 symlink / 路径逃逸；
- 限制 JSONL 总大小和 Result Envelope 大小；
- 非法 UTF-8 / JSON / 非 object JSONL 安全失败；
- Result Envelope 缺字段安全失败；
- protocol version 不兼容返回明确错误；
- run_id / platform 与 Invocation 不一致安全失败；
- 业务使用前递归移除 Cookie、Authorization、Access Token、Refresh Token、API Key、Credential、browser storage 等敏感字段；
- 临时目录在调用结束后清理。

M2-A 不向 subprocess 继承 `DATABASE_URL`、Admin Token 或凭据环境。子进程环境使用白名单，并显式设置 `--enable_ip_proxy false`。

## Safe Subprocess Runner

runner 支持并有离线测试覆盖：

- 正常启动与正常退出；
- timeout；
- cancellation；
- 非零 exit code；
- stdout/stderr 诊断输出超限；
- result missing；
- result too large；
- malformed result；
- partial result envelope；
- browser disconnect 错误分类。

runner 不实现：

- 无限等待；
- 自动无限重启；
- 自动无限 retry；
- 风险后重新登录；
- 风险后自动换账号；
- 代理轮换。

## Adapter Error Mapping

M2-A 标准错误码包括：

- `SUBPROCESS_TIMEOUT`
- `SUBPROCESS_CANCELLED`
- `SUBPROCESS_OUTPUT_TOO_LARGE`
- `NON_ZERO_EXIT`
- `RESULT_MISSING`
- `RESULT_TOO_LARGE`
- `RESULT_MALFORMED`
- `PROTOCOL_VERSION_MISMATCH`
- `BROWSER_DISCONNECTED`
- `AUTH_REQUIRED`
- `LOGIN_EXPIRED`
- `PERMISSION_DENIED`
- `RATE_LIMITED`
- `CAPTCHA_REQUIRED`
- `ACCOUNT_RESTRICTED`
- `ACCOUNT_ABNORMAL`
- `AUTOMATION_DETECTED`
- `NETWORK_TIMEOUT`
- `PARSE_ERROR`
- `UNKNOWN_PLATFORM_ERROR`

Fixture 覆盖 403、406、429、CAPTCHA、login expired、permission denied、automation detected、account restricted、network timeout、browser disconnect 等信号。

Adapter 只负责标准化错误。风险处置仍由主系统现有 `Risk Guard` 判断并落库。认证/登录失效、403/406/429、CAPTCHA、账号受限/异常、自动化检测等风险候选不会进入普通 retry。

## Runtime / Checkpoint / RawSignal

`MediaCrawlerConnector` 注册在现有 `ConnectorRegistry` 的 `mediacrawler` implementation 下，不建立第二套 Registry。

CollectorRuntime 在已有 Budget 和 Run 领取之后调用 Connector。Connector：

- 不导入或创建 ORM；
- 不持有数据库 Session；
- 不提交事务；
- 不调用 AI；
- 不创建 Event；
- 不生成 Embedding。

主系统 `connector_checkpoints` 始终是权威。Invocation 可携带当前 checkpoint；Result 可返回 checkpoint candidate；最终推进仍由 CollectorRuntime 在 RawSignal 成功提交后执行。

M2-A 的实际 vendored runner 当前不生成新的平台增量 checkpoint candidate；后续 vendored Checkpoint / Incremental 增强属于 M2-C。

## Definition 状态语义

M2-A 后：

- MediaCrawler 七个平台仍使用同一个 `connector_type=mediacrawler`；
- Implementation Registry 已存在正式 Adapter implementation；
- 因此可以表达 `implemented=true / adapter available`；
- 不因此产生任何 `validated=true`；
- CI Fixture / Fake subprocess 不写真实 PASSED validation；
- 七平台真实 Schema / Mapper 仍未完成；
- 七平台真实低量验证仍未执行。

## Vendored Source 修改情况

**本批未修改 `third_party/MediaCrawler/` 内任何 vendored source。**

M2-A 所有新增业务边界均位于主系统：

```text
packages/connectors/mediacrawler_adapter/
packages/connectors/
packages/collector_runtime/
packages/risk_guard/
tests/
docs/
```

后续如确需修改 vendored source，必须继续记录在本文件，并保持上游来源、许可证和 local patch 边界清晰。

## 明确未进入范围

M2-A 未实现：

- 七平台完整 Mapper；
- 七平台专属 Schema；
- 真实登录、真实 Cookie、人工扫码；
- 真实平台联网验证；
- vendored Checkpoint / Incremental 增强；
- Account Profile / browser profile 实际接入；
- SignatureProvider；
- HomeFeed / 热榜发现；
- 微博、B站、知乎、抖音、小红书、快手、贴吧实跑；
- Event / EventSignal；
- Embedding；
- 去重 / 聚类；
- AI。

这些仍属于 M2-B / M2-C / M2-D 或之后阶段。

## M2-B local integration

M2-B 继续保持现有 third-party 边界：

- **本批未修改 `third_party/MediaCrawler/` 内任何 vendored source**；
- pinned upstream 仍为 `071c8c0acaece3e82f2532cffb19faeddc9ec1c3`；
- license 仍为 `NON-COMMERCIAL LEARNING LICENSE 1.1`；
- 不更新上游版本，不移除 LICENSE，不改变来源记录。

M2-B 在主系统侧新增：

- 七平台独立 Mapper：微博、B站、知乎、抖音、小红书、快手、百度贴吧；
- Platform Spec：记录平台真实输出结构、有效模式、能力与 Schema 元数据；
- 显式 Platform Mapper Registry：只注册七个平台，未知 platform 明确失败；
- 七平台 `capabilities`；
- 七平台 `config_schema`；
- 七平台 `ui_schema`；
- `implementation_version=mediacrawler-m2b-v1`；
- 统一 `CollectedComment` Domain Model；
- PostgreSQL `raw_signal_comments`；
- 集中式 comment idempotency；
- `MediaCrawlerResultEnvelope → Platform Mapper → RawSignal / CollectedComment → CollectionResult → CollectorRuntime ingestion` 正式转换链。

### 当前保守能力决定

1. **知乎 creator**

   vendored core 存在 creator 逻辑，但当前 pinned CLI 没有正确把 `--creator_id` 接入 `ZHIHU_CREATOR_URL_LIST`。因此 M2-B 当前只声明知乎 search/detail/comments，不声明 creator capability，也不会因为 core 中存在方法就对外声称 creator 可运行。

2. **小红书 detail / creator**

   当前 vendored 小红书 detail/creator 运行依赖带 `xsec_token` 的 URL。主系统普通 config 按既有安全规则不允许保存这类敏感值，因此 M2-B 当前仅开放 `search` 运行模式，并允许 search 显式附带 comments；detail/creator 不开放。

3. **HomeFeed / Hotlist**

   七个平台在 M2-B 均保持关闭，不将统一接口、潜在上游能力或非正式代码路径包装为已实现 capability，也不提前进入 M2-C。

### 评论与数据安全

- `CollectedComment` 不依赖 ORM，不包含凭据，时间统一 UTC-aware；
- `raw_signal_comments` 通过 FK 绑定 RawSignal，并使用 PostgreSQL UNIQUE + `ON CONFLICT DO NOTHING` 提供并发幂等保护；
- 评论幂等优先使用 `platform + content_external_id + external_comment_id`；平台没有稳定 comment ID 时，回退到 `platform + content_external_id + author_id + normalized_text_hash + published_at`；
- 主内容成功后再以独立短事务写评论，部分评论失败不会删除或回滚已成功的 RawSignal；
- 评论默认关闭，subcomments 默认关闭，并继续受 CollectorRuntime Budget 控制；
- Mapper / comment raw payload 继续使用主系统脱敏，平台 token 类查询参数不会进入持久化业务 URL。

### Validation 边界

M2-B 的全部 Fixture / Fake Result Envelope / Mock / PostgreSQL CI 测试只证明主系统工程实现和数据边界正确，**不证明任何真实平台已经 validated PASSED**。

状态仍必须区分：

```text
registered != implemented != validated
```

M2-B 没有连接真实平台、没有登录、没有扫码、没有使用真实 Cookie，也没有生成真实 PASSED validation。真实低量验证仍属于后续 M2-D；vendored Checkpoint / Incremental / Account Profile / SignatureProvider / HomeFeed / Hotlist 增强仍属于 M2-C 或后续阶段。

## M2-D B站低量 search page-size compatibility patch

### 修改范围

本地 vendored 修改严格限定为：

```text
third_party/MediaCrawler/media_platform/bilibili/core.py
```

pinned upstream 继续保持：

```text
071c8c0acaece3e82f2532cffb19faeddc9ec1c3
```

许可证仍为 `NON-COMMERCIAL LEARNING LICENSE 1.1`，未更新 upstream、未改变来源记录。

### pinned upstream 原行为

B站 normal search 的 pinned core 将 API 单页大小固定为 20；当 `CRAWLER_MAX_NOTES_COUNT < 20` 时，还会直接把 `CRAWLER_MAX_NOTES_COUNT` 上抬为 20。结果是主系统即使给出 `requested_limit=1~5`，真实 B站 search client 仍会发出 `page_size=20` 的请求。

这不满足 M2-D 的低量真实验证门槛。仅在 Wrapper / Adapter 层截断 Result Envelope 只能减少主系统最终处理/保存的条数，**无法减少 third-party 已经发出的真实平台请求规模**，因此 Wrapper 无法完全解决这一兼容问题。

### 本地最小 patch

本地 patch 只调整 B站 `search_by_keywords` 的 page-size / pagination：

- 移除 `<20 → 20` 的 `CRAWLER_MAX_NOTES_COUNT` 强制上抬；
- 继续使用 B站现有 client 已正式支持的 `page_size` 参数，不新增或猜测 API 参数；
- 单次 normal search 使用稳定 `page_size=min(20, CRAWLER_MAX_NOTES_COUNT)`；
- `requested_limit=1/3/5/20` 时首次 client 调用的 `page_size` 分别为 `1/3/5/20`；
- `requested_limit>20` 时保持固定 `page_size=20`，以 `page + page_size` 的既有分页模型继续请求；
- 使用有限 `page_count=ceil(requested_limit/page_size)`，避免无限循环；
- page number 从 `START_PAGE` 连续递增，单次运行不改变 page_size，避免因分页窗口移动产生重复或漏页；
- 最后一页仅处理剩余 requested items；若服务端提前返回短页则停止继续翻页。

离线回归测试直接抽取并执行 vendored `search_by_keywords` 方法，对 fake client 记录的 `(page, page_size)` 调用进行断言。因此 `requested_limit=5 → 首次真实 client 参数 page_size=5` 的工程语义由测试覆盖，而不是“请求 20 后本地截断 5”。

### 明确未修改

本次 patch **不涉及**：

- B站登录方式；
- Cookie；
- Browser Profile / CDP；
- Signature；
- Risk Guard / 风险映射；
- proxy / IP 轮换；
- stealth / 指纹；
- 账号状态；
- CAPTCHA；
- 其他平台；
- MediaCrawler upstream commit。

本次仍未进行真实联网、登录、扫码或真实 Smoke。

### 后续 subtree pull 检查点

未来重新同步 / subtree pull MediaCrawler 时，必须重点检查：

```text
third_party/MediaCrawler/media_platform/bilibili/core.py
BilibiliCrawler.search_by_keywords
```

重点确认上游是否仍存在固定 `page_size=20` 或 `<20 → 20` 的强制上抬逻辑，以及上游是否已经提供等价的低量分页能力。若上游已经原生解决，应优先删除本地 patch；若发生冲突，不得机械保留或覆盖，应重新验证 `page + page_size` 窗口、`START_PAGE`、requested limit 与最终页语义。
