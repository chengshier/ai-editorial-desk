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
