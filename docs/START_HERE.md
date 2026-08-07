# AI 编辑部项目开发入口

## 当前阶段

- **M1-A：已完成并合并**；
- **M1-B：已完成并合并**；
- **M1-C：已完成并合并**；
- **M1-D：已完成并通过 CI，PR #6 已合并**；
- **M1：已形成当前 `main` 完整基线**；
- **M2-A：当前开发阶段，仅建立 MediaCrawler 主系统集成层**；
- **M2-B / M2-C / M2-D：尚未开始**。

M2-A 分支必须从最新 `main` 创建，当前分支为：

```text
feature/m2a-mediacrawler-integration
```

M2-A PR 合并前不要从 feature 分支派生 M2-B，也不要提前进入后续子阶段。

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

## M2-A 唯一目标

只建立以下正式边界：

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

不得重建第二套 Runtime、Run、Checkpoint、Risk Guard、RawSignal 或 Registry。

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

M2-A 不更新上游版本。本阶段通过 Wrapper / Adapter 完成集成，**不修改 vendored MediaCrawler 业务源码**。上游来源、LICENSE 与 third-party 记录必须保留。

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
- M2-A 不依赖 MediaCrawler 内部数据库。

## Definition 状态语义

M2-A 完成后 MediaCrawler 可以表达：

```text
registered = true
implemented = true / adapter available
enabled = 取运营数据库状态
validated = 仍需后续真实人工低量验证
```

**Fixture / Mock CI 不得自动生成 PASSED validation。**

M2-A 不包含七平台完整 Mapper / Schema，因此“implementation available”不等于七平台已经可用于真实生产采集。

## M2-A 测试边界

全部离线：

- Invocation 序列化/平台/mode/limit/protocol；
- Result 正常/malformed/version mismatch/missing fields/oversized；
- subprocess success/timeout/cancel/nonzero/no result/malformed/partial；
- 403/406/429/CAPTCHA/login expired/permission/automation/account restricted/network timeout/browser disconnect；
- Fake MediaCrawler Runtime：Run 状态、RawSignal 入库、幂等、Checkpoint、Risk、Budget。

不连接真实平台，不登录，不扫码，不使用真实 Cookie。

## CI

M2-A 继续执行现有完整 CI：

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

## M2-A 明确禁止范围

本阶段不做：

- 七平台完整 Mapper；
- 七平台专属 Schema；
- 真实登录 / Cookie / 扫码；
- 真实平台联网或真实 Smoke；
- vendored Checkpoint / Incremental 增强；
- Account/Profile vendored 增强；
- SignatureProvider；
- HomeFeed / 热榜发现；
- 微博 / B站 / 知乎 / 抖音 / 小红书 / 快手 / 贴吧实跑；
- Event / EventSignal；
- Embedding；
- 去重 / 聚类；
- AI。

这些属于 M2-B / M2-C / M2-D 或之后阶段。

## 开发原则

- 一个子阶段一个独立分支、独立 PR；
- 前一个 PR 合并后才进入下一个；
- 不从 feature 分支继续派生下一阶段；
- Commit / PR 使用中文；
- PR 不自行合并；
- 风险错误不普通重试；
- 不自动换号、不代理轮换、不处理/破解验证码、不伪造指纹、不绕过平台限制；
- 第三方源码不承载主系统业务职责。
