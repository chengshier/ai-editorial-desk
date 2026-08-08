# M2 Acceptance Report

> 最终阶段语义：**M2 Engineering Complete；M2 Real Smoke Validation = DEFERRED / NOT_TESTED；M2 Real-world Validation 尚未完成。**

## 1. 验收语义

本报告严格区分：

- **M2 Engineering Complete**：M2-A / M2-B / M2-C 工程实现，以及 M2-D offline engineering/readiness 已完成并通过当前离线 CI Gate；
- **Real Smoke Validation Deferred / NOT_TESTED**：当前没有人工真实账号/Profile/平台访问证据，可以延后，但不得解释为 PASSED；
- **Real Smoke Verified**：未来真实人工低量平台访问完成，并有真实 `SUCCEEDED` Test/Manual Run 与当前 implementation_version 对应的 PASSED Validation；
- **M2 Real-world Validation Complete**：当前**不成立**。

允许 M3 Engineering 在 PR #10 合并后开始，不代表 M2 Real Smoke VERIFIED。

---

## 2. M2 Engineering Gate

状态：**COMPLETE**。

### M2-A Adapter / Runtime

- MediaCrawler 主系统 Adapter / Connector；
- Versioned Invocation / Result Envelope；
- 受控 subprocess、结果大小与脱敏；
- 复用现有 CollectorRuntime / Budget / Risk Guard / Checkpoint；
- 不建立第二套 Runtime / Registry / ORM 事务边界。

### M2-B Mapper / Schema / Comments

- 七平台独立 Mapper；
- capabilities / config_schema / ui_schema；
- RawSignal / CollectedComment；
- `raw_signal_comments`；
- 评论幂等与 Budget；
- Web 动态 SchemaForm。

### M2-C Checkpoint / Incremental / Profile / Signature / Risk

- Protocol 1.1；
- Checkpoint / Resume；
- Incremental；
- Account / Browser Profile abstraction；
- SignatureProvider；
- PlatformRiskSignal；
- 风险不进入普通 retry。

M2-C 最终 CI #131 success；合并后 main CI #132 success。

### M2-D Offline Engineering / Readiness

- dedicated low-volume Smoke Harness；
- B站低量 search compatibility；
- 知乎低量 search compatibility；
- 微博低量 Search 源码审计与 fail-closed Gate；
- `docs/M2_REAL_SMOKE_SETUP.md`；
- Environment Preflight；
- login-only Preflight；
- Account / Profile / Budget / Risk / Validation Gate；
- 三个平台真实 Validation 事实文档；
- Acceptance documentation。

---

## 3. M2-D 最终工程基线

开发分支：

```text
feature/m2d-first-platform-validation
```

PR #10：

```text
feat: 完成 M2-D 离线验证准备与工程收口
```

M2-D 最终工程 HEAD（文档状态收口前的工程基线）：

```text
54149c4fa83922a270a8fe10eaed4499945ca0e6
```

GitHub Actions：

```text
CI #177
run id 31242273861
completed / success
```

最终工程验收：

| 项目 | 结果 |
|---|---|
| Ruff | success |
| mypy | success / 128 source files |
| pytest | **240 passed / 1 warning** |
| Alembic `upgrade head → downgrade -1 → upgrade head → downgrade base → upgrade head` | success |
| Definition 第一次同步 | `created=11 / updated=0 / unchanged=0 / failed=0` |
| Definition 第二次同步 | `created=0 / updated=0 / unchanged=11 / failed=0` |
| Web lint / typecheck / test / build | success |
| GitHub changed files | 25 |

CI / Fixture / Fake 全部是离线工程证据，不产生真实平台 Run 或 PASSED Validation。

---

## 4. M2-D 安全边界

- 首批目标仅 B站 / 知乎 / 微博；
- real smoke 只允许显式人工 actor + 明确 confirmation；
- CI / Mock / Test 环境禁止 real smoke；
- requested_limit <= 5；
- detail=1；
- comments=1 个主内容 × 最多 5 条一级评论；
- subcomments=false；
- concurrency=1；
- proxy=false；
- 单账号每天最多 3 个 Test/Manual smoke Run；
- stable Browser Profile；
- visible existing CDP browser；
- 禁止自动 qrcode / phone / cookie login；
- CDP 失败禁止回退到 vendored 标准浏览器路径；
- 抖音 / 小红书 / 快手 / 百度贴吧 fresh Definition 默认 disabled；
- 403 / 406 / 429 / CAPTCHA / automation detected / login expired / restricted / blocked / abnormal 等风险立即停止；
- 不重试、不换号、不换 Profile、不做 proxy rotation；
- REAL SMOKE 不进入 CI。

---

## 5. Search 低量 Engineering Gate

| 平台 | pinned 原始行为 | 当前 Engineering Gate | Real Smoke |
|---|---|---|---|
| B站 | normal search 固定/上抬到 20 | **READY** | NOT_TESTED |
| 知乎 | normal search 固定/上抬到 20 | **READY** | NOT_TESTED |
| 微博 | core 约 10；client 无已证实低量参数 | **BLOCKED / ACCEPTED KNOWN LIMITATION** | NOT_TESTED |

### 5.1 B站

最小 vendored patch：

```text
third_party/MediaCrawler/media_platform/bilibili/core.py
```

语义：

- 不再 `<20 → 20`；
- 使用 client 已支持的 `page_size`；
- `requested_limit=1/3/5` → client `page_size=1/3/5`；
- `>20` 固定 `page_size=20` 正常有限分页；
- 不修改登录/Cookie/CDP/signature/Risk/proxy/stealth/account。

状态：**ENGINEERING READY；REAL SMOKE = NOT_TESTED；Validation = NOT_TESTED。**

### 5.2 知乎

pinned client 已明确支持：

```text
page_size
→ offset=(page-1)*page_size
→ limit=page_size
```

最小 vendored patch：

```text
third_party/MediaCrawler/media_platform/zhihu/core.py
```

语义：

- 不猜测 API 参数；
- 不新增协议；
- `requested_limit=1/3/5` → client `page_size=1/3/5`；
- `>20` 固定 `page_size=20`；
- 单次运行 page_size 稳定，保持 offset 窗口连续；
- 有限 page count；
- 最后一页只处理剩余 requested items；
- 不修改登录/Cookie/CDP/signature/Risk/proxy/stealth/account。

状态：**ENGINEERING READY；REAL SMOKE = NOT_TESTED；Validation = NOT_TESTED。**

### 5.3 微博

pinned `WeiboClient.get_note_by_keyword` 当前只有已证实的 `keyword / page / search_type`；请求参数中没有已实现、已证实的 `page_size / count / limit`。

因此：

```text
WEIBO_LOW_VOLUME_SEARCH = BLOCKED
ACCEPTED KNOWN LIMITATION
```

接受该限制的原因：

- 不猜 API 参数；
- 不逆向接口；
- 不扩展 Signature；
- 不通过请求 10 条后本地截断伪造 `<=5`；
- 不为完成 Gate 绕过请求量限制。

未来只有以下任一条件成立才重新打开：

1. upstream 明确提供低量参数；
2. 新 pinned version 有可验证实现；
3. 有正规源码证据表明现有接口支持低量请求。

该限制**不再阻塞 M3 Engineering**。

微博 Detail 工程入口存在，但 REAL SMOKE = NOT_TESTED；Validation = NOT_TESTED。

---

## 6. Real Smoke Gate

状态：**DEFERRED / NOT_TESTED**。

| 平台 | Real Run ID | REAL SMOKE | Validation |
|---|---|---|---|
| B站 | 无 | NOT_TESTED | NOT_TESTED |
| 知乎 | 无 | NOT_TESTED | NOT_TESTED |
| 微博 | 无 | NOT_TESTED | NOT_TESTED |

当前没有：

- 真实登录；
- 扫码；
- Cookie 注入；
- 真实平台内容请求；
- 真实 SUCCEEDED Test/Manual Run evidence；
- PASSED Validation。

Deferred 不得自动转换为 PASSED，也不得通过数据库伪造真实 Validation。

详细平台事实记录：

- `platform-validation/bilibili_m2_validation.md`
- `platform-validation/zhihu_m2_validation.md`
- `platform-validation/weibo_m2_validation.md`

---

## 7. Real Smoke Deferred 的正式策略

当前用户暂时无法配置本地真实联调环境。工程阶段不再无限等待该外部条件：

- M2 Engineering = COMPLETE；
- M2 Real Smoke Validation = DEFERRED / NOT_TESTED；
- M3 / M4 / M5 Engineering 可继续；
- M5 宣布“真实世界 / Production Validation 完成”前，必须至少补一次真实端到端平台 Smoke；
- 未来优先从 B站或知乎开始；
- 真实 Smoke 继续受 Risk Guard / Budget / Account / Browser Profile / no-proxy-rotation 等边界约束。

这项策略已正式记录在 `docs/DECISIONS.md`。

---

## 8. M3 Gate

状态：

```text
ALLOWED AFTER PR #10 MERGE
```

前提：

1. PR #10 仍由人工决定是否合并，不自行合并；
2. 合并后从最新 `main` 开启独立 M3 窗口；
3. 从最新 `main` 创建独立 M3-A 分支；
4. 不从 M2-D feature branch 派生；
5. M3 开始不代表 M2 Real Smoke VERIFIED。

M3 next：Event / EventSignal、Embedding、Dedup、Clustering。

**当前 M3 仍未开始。**

---

## 9. 最终结论

```text
M2 Engineering Gate: COMPLETE
M2 Real Smoke Validation: DEFERRED / NOT_TESTED
M2 Real-world Validation: NOT COMPLETE
Weibo Low-volume Search: BLOCKED / ACCEPTED KNOWN LIMITATION
M3 Engineering Gate: ALLOWED AFTER PR #10 MERGE
```

不得将本报告简化为“M2 Real-world Validation Complete”。
