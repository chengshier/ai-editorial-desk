# AI 编辑部项目开发入口

## 当前阶段

- **M1：已完成并合并**；
- **M2-A：已完成并合并**；
- **M2-B：已完成并合并**；
- **M2-C：已完成并合并**；
- **M2-D Engineering：已完成，等待 PR #10 合并**；
- **M2 Real Smoke Validation：DEFERRED / NOT_TESTED**；
- **M2 Engineering：COMPLETE**；
- **M2 Real-world Validation：NOT COMPLETE**；
- **M3：未开始，但 PR #10 合并后允许进入**。

当前 M2-D 分支：

```text
feature/m2d-first-platform-validation
```

当前 PR：

```text
#10 feat: 完成 M2-D 离线验证准备与工程收口
```

PR #10 合并后，必须从**最新 `main`** 独立创建 M3-A 分支并开启独立 M3 窗口；**不要从 `feature/m2d-first-platform-validation` 继续派生 M3**。

Real Smoke 延后只表示当前本地真实联调条件未就绪，不允许把 NOT_TESTED 改写为 PASSED，也不代表 M2 Real-world Validation 已完成。

## 必读文档顺序

1. `DECISIONS.md`
2. `M2_ACCEPTANCE_REPORT.md`
3. `M2_REAL_SMOKE_SETUP.md`
4. `M1_ACCEPTANCE_REPORT.md`
5. `AI编辑部_综合开发实施规划_V1.2.md`
6. `AI编辑部_技术开发文档_V1.2.md`
7. `AI编辑部_PRD_V1.2.md`
8. `CHANGELOG.md`
9. `MEDIACRAWLER_LOCAL_CHANGES.md`
10. `../third_party/MEDIACRAWLER_UPSTREAM.md`
11. `../third_party/README.md`

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

M2-A / M2-B / M2-C 均保持主系统职责在 Wrapper / Adapter / Mapper / Runtime；M2-D 仅对以下两个 vendored core 做经过明确授权的最小低量 search compatibility patch：

```text
third_party/MediaCrawler/media_platform/bilibili/core.py
third_party/MediaCrawler/media_platform/zhihu/core.py
```

两处都不修改登录、Cookie、CDP、Signature、Risk Guard、proxy、stealth、CAPTCHA 或账号逻辑。微博及其他平台没有新增 vendored patch。上游来源、LICENSE 与 third-party 记录必须保留。

## 当前 Versioned Protocol

`MediaCrawlerInvocation` / `MediaCrawlerResultEnvelope` 当前主系统协议版本：

```text
1.1
```

Invocation 只传可 JSON 序列化的 Domain Model，不传 ORM、Session、DATABASE_URL、Admin Token、明文 Cookie/Token/Authorization。

Result Envelope 继续携带 run/platform/status/items/comments/checkpoint/counters/warnings/risk_events/errors/timestamps 等标准字段；stdout/stderr 只作为受限诊断，不作为业务数据协议。

## Safe Subprocess

当前 runner：

- 每个 Run 创建独立安全临时目录；
- `--save_data_path` 由主系统决定；
- 使用 JSONL / Result Envelope 作为 vendored 输出边界；
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
- CollectorRuntime 调用 Connector 前继续做 Preflight、Budget 和 Run 领取；
- Connector 不写 ORM、不持有 Session、不自行 commit；
- 主系统 `connector_checkpoints` 始终权威；
- Invocation 携带 checkpoint，Result 返回 candidate；
- 只有 RawSignal 成功提交后 Runtime 才推进 Checkpoint；
- Incremental / Resume 由 M2-C 工程基线正式接通；
- 主系统不依赖 MediaCrawler 内部数据库。

## M2-B 七平台 Mapper 与配置能力

M2-B 在 M2-A Result Envelope 之后建立显式平台映射层：

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

M2-B 完成七平台 Mapper、capabilities/config_schema/ui_schema、`CollectedComment`、`raw_signal_comments`、评论幂等/Budget 与 Web 动态 SchemaForm。M2-B 当时的 `implementation_version` 为 `mediacrawler-m2b-v1`；M2-C 后当前版本已演进为 `mediacrawler-m2c-v1`。

## M2-C 已完成边界

M2-C 已完成并合并，核心工程边界包括：

- Protocol 1.1；
- Checkpoint / Resume；
- Incremental；
- Account / Browser Profile abstraction；
- SignatureProvider；
- PlatformRiskSignal；
- 风险信号不进入普通 retry；
- stable Browser Profile 与受控本地 runtime 边界；
- M2-C 最终 CI #131 success，合并后 main CI #132 success。

M2-C 没有通过 CI 伪造任何真实平台 PASSED Validation。

## M2-D Engineering 已完成边界

M2-D 当前只完成**离线工程与真实验证准备**，不声称已完成真实平台验证。

已完成：

- 专用低量 Smoke Harness；
- B站低量 normal search compatibility：`requested_limit=1/3/5` → client `page_size=1/3/5`；
- 知乎低量 normal search compatibility：复用 pinned client 已有 `page_size → offset/limit`，`requested_limit=1/3/5` → client `page_size=1/3/5`；
- 微博源码审计：没有已证实的 `page_size/count/limit`，`WEIBO_LOW_VOLUME_SEARCH = BLOCKED`；
- `docs/M2_REAL_SMOKE_SETUP.md`；
- `python -m scripts.check_m2_smoke_environment` 零平台请求环境 preflight；
- `python -m scripts.check_m2_smoke_login` 未来人工登录后的 login-only preflight；
- Account / Profile / Budget / Risk / Validation 的真实 Smoke Gate 说明；
- B站 / 知乎 / 微博平台 Validation 事实记录。

当前 M2-D 工程 Gate：

| 平台 | Detail Engineering | Low-volume Search | Real Smoke | Validation |
|---|---|---|---|---|
| B站 | READY | READY | NOT_TESTED | NOT_TESTED |
| 知乎 | READY | READY | NOT_TESTED | NOT_TESTED |
| 微博 | READY（入口存在） | BLOCKED / Accepted Known Limitation | NOT_TESTED | NOT_TESTED |

微博 Search BLOCKED 已正式作为 **Accepted Known Limitation** 接受，不继续阻塞 M3 Engineering。只有 upstream 明确提供低量参数、新 pinned version 有可验证实现，或正规源码证据证明现有接口支持低量请求时，才重新打开该 Gate。

## Definition / Validation 状态语义

连接器状态必须继续区分：

```text
registered != implemented != enabled != validated
```

- `registered`：Definition 已注册；
- `implemented`：主系统已有可调用实现；
- `enabled`：当前运营配置允许调用；
- `validated`：真实人工低量验证状态。

**Fixture / Mock / CI 不得自动生成 PASSED validation。** Real Smoke Deferred 也绝不能转换为 PASSED。

## M2 最终工程 CI

M2-D 最终工程 HEAD：

```text
54149c4fa83922a270a8fe10eaed4499945ca0e6
```

对应 GitHub Actions：

```text
CI #177
run id 31242273861
completed / success
```

Python / PostgreSQL：

```text
ruff check .                    success
mypy apps packages              128 source files / success
pytest                          240 passed / 1 warning
Alembic full round trip         success
Definition sync #2              created=0 / updated=0 / unchanged=11 / failed=0
```

Web：

```text
lint / typecheck / test / build success
```

该 CI 没有真实平台访问、登录、扫码、Cookie 注入或真实 PASSED Validation。

## Real Smoke 延后策略

正式阶段语义：

```text
M2 Engineering Complete
M2 Real Smoke Validation Deferred / NOT_TESTED
M2 Real-world Validation NOT COMPLETE
```

当前用户暂时无法配置本地真实联调环境，因此真实 Smoke 可以 Deferred，而 M3/M4/M5 Engineering 不再被该环境条件无限阻塞。

未来真实 Smoke 仍必须遵守：dedicated low-value Account、stable Browser Profile、visible existing CDP、极低 Budget、concurrency=1、proxy=false、Risk Guard、403/406/429/CAPTCHA/automation/login/account 异常立即停止、不重试、不换号、不换 Profile、不做 proxy rotation。

在 M5 宣布“真实世界 / Production Validation 完成”之前，必须至少补一次真实端到端平台 Smoke；优先从 B站或知乎开始。

## PR #10 合并后的 M3 入口

PR #10 合并后：

1. 切回并同步最新 `main`；
2. 确认 PR #10 的 merge 后 main CI 正常；
3. 开启独立 M3 窗口；
4. 从最新 `main` 创建独立 M3-A 分支；
5. 不从 M2-D feature branch 派生。

M3 next：Event / EventSignal、Embedding、Dedup、Clustering。

**当前 M3 尚未开始。**

## 开发原则

- 一个子阶段一个独立分支、独立 PR；
- 前一个 PR 合并后才进入下一个工程阶段；
- 不从 feature 分支继续派生下一阶段；
- Commit / PR 使用中文；
- PR 不自行合并；
- Engineering Complete 与 Real-world Validation Complete 必须分离表达；
- Deferred / NOT_TESTED 不得伪造 PASSED；
- 风险错误不普通重试；
- 不自动换号、不代理轮换、不处理/破解验证码、不伪造指纹、不绕过平台限制；
- 第三方源码不承载主系统业务职责。
