# AI 编辑部项目开发入口

## 当前阶段

- **M1-A：已完成并合并**；
- **M1-B：已完成并合并**；
- **M1-C：已完成并合并**；
- **M1-D：已完成并通过 CI，PR #6 已合并**；
- **M1：已形成当前 `main` 完整基线**；
- **M2-A：已完成并合并**；
- **M2-B：已完成开发与 CI 验收，等待 PR #8 合并**；
- **M2-C：未开始**；
- **M2-D：未开始**；
- **M2 整体：尚未完成**。

当前 M2-B 分支：

```text
feature/m2b-platform-mappers
```

下一步必须在 PR #8 合并后，从最新 `main` 独立创建 M2-C 分支；不要从 M2-B feature 分支继续派生，也不要提前进入 M2-C / M2-D。

## 必读文档顺序

1. `DECISIONS.md`
2. `M1_ACCEPTANCE_REPORT.md`
3. `AI编辑部_综合开发实施规划_V1.2.md`
4. `AI编辑部_技术开发文档_V1.2.md`
5. `AI编辑部_PRD_V1.2.md`
6. `CHANGELOG.md`
7. `MEDIACRAWLER_LOCAL_CHANGES.md`
8. `../third_party/MEDIACRAWLER_UPSTREAM.md`
9. `../third_party/README.md`

冲突优先级：DECISIONS → 综合开发实施规划 → 技术开发文档 → PRD。

## M1 已完成基线

M1 已建立：

- Async SQLAlchemy / Alembic / PostgreSQL 16 + pgvector；
- Connector Definition / Instance / Platform Account；
- Source / Raw Signal / Collection Budget；
- CollectionTask / CollectorRuntime；
- Run 原子领取、stale 检查、人工 retry/cancel；
- Checkpoint 乐观更新和安全 reset；
- Risk Guard / PlatformRiskEvent / Account 状态；
- RSS / Manual URL / 百度实时 Hotlist；
- PostgreSQL Scheduler / Lease / 时间槽去重；
- Connector Validation；
- React + Vite + TypeScript 连接器工作台。

详细验收证据见 `M1_ACCEPTANCE_REPORT.md`。

## M2-A 已完成边界

M2-A 建立以下正式边界：

```text
CollectionTask
→ CollectorRuntime
→ MediaCrawlerConnector
→ MediaCrawlerAdapter
→ 受控 subprocess
→ third_party/MediaCrawler
→ 标准结果协议
→ RawSignal
```

没有重建第二套 Runtime、Run、Checkpoint、Risk Guard、RawSignal 或 Registry。

## MediaCrawler 固定边界

Vendored 目录：

```text
third_party/MediaCrawler/
```

固定上游 commit：

```text
071c8c0acaece3e82f2532cffb19faeddc9ec1c3
```

许可证：`NON-COMMERCIAL LEARNING LICENSE 1.1`。

M2-A / M2-B 均不更新上游版本，通过 Wrapper / Adapter / Mapper 完成主系统集成，**不修改 vendored MediaCrawler 业务源码**。上游来源、LICENSE 与 third-party 记录必须保留。

## M2-A Versioned Protocol

### Invocation

`MediaCrawlerInvocation` 当前版本：

```text
1.0
```

包含：

- protocol_version
- run_id
- platform
- mode
- source_id
- keyword
- creator_id
- content_ids
- requested_limit
- comment_limit
- include_comments
- include_subcomments
- checkpoint
- account_ref
- browser_profile_ref
- timeout_seconds

Invocation 使用 Pydantic v2，必须可 JSON 序列化；不传 ORM、Session、DATABASE_URL、Admin Token、明文 Cookie/Token/Authorization。

### Result

`MediaCrawlerResultEnvelope` 包含：

- protocol_version
- run_id
- platform
- status
- items
- comments
- checkpoint
- counters
- warnings
- risk_events
- errors
- started_at
- finished_at

stdout/stderr 只作为受限诊断，不作为业务数据协议。

## Safe Subprocess

M2-A runner：

- 每个 Run 创建独立安全临时目录；
- `--save_data_path` 由主系统决定；
- 使用 JSONL 作为 vendored 输出边界，并由主系统生成/校验 Result Envelope；
- 限制 JSONL、Envelope 和 stdout/stderr 大小；
- 拒绝结果 symlink / 路径逃逸；
- malformed JSON、missing result、version mismatch 明确失败；
- timeout 与 cancellation 会终止 subprocess；
- 非零 exit code 进入统一错误映射；
- 不无限等待、不无限重启、不无限 retry；
- 不把 DATABASE_URL、Admin Token 或凭据环境传入 third-party；
- `--enable_ip_proxy false`，不做代理轮换。

## Error / Risk Guard

标准 Adapter Error 至少覆盖：

```text
SUBPROCESS_TIMEOUT
SUBPROCESS_CANCELLED
SUBPROCESS_OUTPUT_TOO_LARGE
NON_ZERO_EXIT
RESULT_MISSING
RESULT_TOO_LARGE
RESULT_MALFORMED
PROTOCOL_VERSION_MISMATCH
BROWSER_DISCONNECTED
AUTH_REQUIRED
LOGIN_EXPIRED
PERMISSION_DENIED
RATE_LIMITED
CAPTCHA_REQUIRED
ACCOUNT_RESTRICTED
ACCOUNT_ABNORMAL
AUTOMATION_DETECTED
NETWORK_TIMEOUT
PARSE_ERROR
UNKNOWN_PLATFORM_ERROR
```

Adapter 只报告标准错误；现有 Risk Guard 决定处置。以下风险候选不得落入普通 retry：

- 403 / 406 / 429；
- CAPTCHA / 验证码；
- 检测到自动化或 AI 操作；
- account blocked / restricted / abnormal；
- repeated login invalidation / login expired；
- `-104` 等已有风险码。

## Registry / Runtime / Checkpoint

- `MediaCrawlerConnector` 继续使用现有 `ConnectorRegistry`；
- 七个平台继续共享 `connector_type=mediacrawler`，platform 由 Definition 决定；
- CollectorRuntime 继续在调用 Connector 前做 Preflight、Budget 和 Run 领取；
- Connector 不写 ORM、不持有 Session、不自行 commit；
- 主系统 `connector_checkpoints` 始终权威；
- Invocation 可携带 checkpoint，Result 可返回 candidate；
- 只有 RawSignal 成功提交后 Runtime 才推进 Checkpoint；
- M2-A / M2-B 不依赖 MediaCrawler 内部数据库。

## M2-B 七平台 Mapper 与配置能力

M2-B 在 M2-A Result Envelope 之后新增显式平台映射层：

```text
MediaCrawlerResultEnvelope
→ Platform Mapper Registry
→ 七平台 Mapper
→ RawSignal / CollectedComment
→ CollectionResult
→ CollectorRuntime ingestion
```

七平台当前有效运行能力：

| 平台 | search | detail/id | creator | comments | homefeed | hotlist |
|---|---:|---:|---:|---:|---:|---:|
| 微博 | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| B站 | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| 知乎 | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| 抖音 | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| 小红书 | ✅ | ❌ | ❌ | ✅* | ❌ | ❌ |
| 快手 | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| 百度贴吧 | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |

`*` 小红书当前只开放 `search` 运行模式，可在 search 中显式附带 comments；detail/creator 不开放。

关键保守边界：

- 微博 / B站 / 抖音 / 快手 / 百度贴吧：开放 search/detail/creator/comments；
- 知乎：vendored core 存在 creator 逻辑，但 pinned CLI 未正确把 `creator_id` 接入 `ZHIHU_CREATOR_URL_LIST`，因此当前 creator 有效能力为 false；
- 小红书：detail/creator 依赖带 `xsec_token` 的 URL，普通 config 不允许保存这类敏感值，因此当前仅开放 search，并允许 search 附带 comments；
- 七平台：homefeed / hotlist 均未开放，不提前进入 M2-C。

M2-B 同时完成：

- 七平台独立 Mapper 与显式 Mapper Registry；
- 七平台 `capabilities` / `config_schema` / `ui_schema`；
- `implementation_version=mediacrawler-m2b-v1`；
- `CollectedComment` Domain Model；
- PostgreSQL `raw_signal_comments`；
- 评论统一幂等与数据库并发唯一保护；
- 评论 Budget 预留/结算；
- Web 动态 SchemaForm 条件显示增强。

## Definition 状态语义

连接器状态必须继续区分：

```text
registered != implemented != validated
```

- `registered`：Definition 已注册；
- `implemented`：主系统已有可调用实现；
- `validated`：真实人工低量验证状态。

**Fixture / Mock CI 不得自动生成 PASSED validation。** M2-B 没有任何真实平台被 CI 自动标记 PASSED。

## M2-A / M2-B 测试边界

全部离线：

- Invocation 序列化/平台/mode/limit/protocol；
- Result 正常/malformed/version mismatch/missing fields/oversized；
- subprocess success/timeout/cancel/nonzero/no result/malformed/partial；
- 403/406/429/CAPTCHA/login expired/permission/automation/account restricted/network timeout/browser disconnect；
- Fake MediaCrawler Runtime：Run 状态、RawSignal 入库、幂等、Checkpoint、Risk、Budget；
- 七平台真实 JSONL 结构 Fixture Mapper；
- 评论 Domain / FK / 幂等 / 并发唯一 / parent / CASCADE / raw_payload 脱敏；
- capability / allowed_modes 在 subprocess 前拒绝；
- Web mode 与评论字段条件展示。

不连接真实平台，不登录，不扫码，不使用真实 Cookie。

## CI

M2-B 继续执行现有完整 CI：

```bash
ruff check .
mypy apps packages
pytest
alembic upgrade head
alembic downgrade -1
alembic upgrade head
alembic downgrade base
alembic upgrade head
python -m scripts.sync_connector_definitions
python -m scripts.sync_connector_definitions
```

Web：

```bash
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

`third_party/MediaCrawler` 不纳入根 Ruff。

## 当前未开始范围

M2-C / M2-D 仍未开始，当前不做：

- 真实登录 / Cookie / 扫码；
- 真实平台联网或真实 Smoke；
- vendored Checkpoint / Incremental 增强；
- Account/Profile vendored 增强；
- SignatureProvider；
- HomeFeed / Hotlist 真实发现；
- 微博 / B站 / 知乎 / 抖音 / 小红书 / 快手 / 贴吧真实低量验证；
- Event / EventSignal；
- Embedding；
- 去重 / 聚类；
- AI。

PR #8 合并后才进入 M2-C；M2-D 继续等待后续阶段。

## 开发原则

- 一个子阶段一个独立分支、独立 PR；
- 前一个 PR 合并后才进入下一个；
- 不从 feature 分支继续派生下一阶段；
- Commit / PR 使用中文；
- PR 不自行合并；
- 风险错误不普通重试；
- 不自动换号、不代理轮换、不处理/破解验证码、不伪造指纹、不绕过平台限制；
- 第三方源码不承载主系统业务职责。
