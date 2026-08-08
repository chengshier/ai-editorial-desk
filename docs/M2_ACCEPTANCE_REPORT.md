# M2 Acceptance Report

> 当前状态：**M2 工程实现接近完成；M2-D offline readiness 持续收口。B站 / 知乎 / 微博 REAL SMOKE 均未执行，M2 不能标记完成。**

## 1. 验收语义

本报告严格区分：

- **ENGINEERING / CI READY**：源码、Fixture / Fake、PostgreSQL、静态检查、Migration、Definition sync、Web 工程验收达到当前离线 Gate；
- **REAL SMOKE NOT RUN**：没有人工真实账号/Profile/平台访问证据；
- **REAL SMOKE VERIFIED**：真实人工低量平台访问完成，并有真实 `SUCCEEDED` Test/Manual Run 与当前 implementation_version 对应的 PASSED Validation。

任何 `ENGINEERING / CI READY` 都不能替代真实 Smoke。

---

## 2. M2-A

| 项目 | 状态 |
|---|---|
| MediaCrawler 主系统 Adapter / Connector | CI VERIFIED |
| Versioned Invocation / Result Envelope | CI VERIFIED |
| 受控 subprocess / 结果大小 / 脱敏 | CI VERIFIED |
| Runtime / Budget / Risk Guard / Checkpoint 复用 | CI VERIFIED |
| third_party 本地修改 | 0 |
| Real Smoke | NOT_REQUIRED_FOR_M2-A |

## 3. M2-B

| 项目 | 状态 |
|---|---|
| 七平台独立 Mapper | CI VERIFIED |
| 七平台 capabilities / config_schema / ui_schema | CI VERIFIED |
| RawSignal / CollectedComment | CI VERIFIED |
| `raw_signal_comments` / 评论幂等 / Budget | CI VERIFIED |
| HomeFeed / Hotlist | 七平台保持 false |
| Real Smoke | NOT_REQUIRED_FOR_M2-B |

## 4. M2-C

| 项目 | 状态 |
|---|---|
| Protocol 1.1 | CI VERIFIED |
| Checkpoint / Resume | CI VERIFIED |
| Incremental | CI VERIFIED |
| Account / Browser Profile abstraction | CI VERIFIED |
| SignatureProvider | CI VERIFIED |
| PlatformRiskSignal | CI VERIFIED |
| 风险不进入普通 retry | CI VERIFIED |
| M2-C 最终 CI | #131 success；merge 后 main CI #132 success |
| third_party 本地修改 | 0 |

---

## 5. M2-D Offline Readiness

开发分支：`feature/m2d-first-platform-validation`

PR：#10 `feat: 完成 M2-D 首批国内平台低量验证`

PR 保持 Open，不自行合并；M3 未开始。

当前安全边界：

- 首批目标仅 B站 / 知乎 / 微博；
- dedicated Smoke Harness；
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
- REAL SMOKE 不进入 CI。

### 5.1 本地环境 readiness

新增：

- `docs/M2_REAL_SMOKE_SETUP.md`：从 Python/Node/PostgreSQL/pgvector 到 Account/Budget/CDP/Validation 的本地人工 Smoke 操作手册；
- `python -m scripts.check_m2_smoke_environment`：零平台请求、只读本地环境 preflight；
- `python -m scripts.check_m2_smoke_login`：未来人工登录后使用的 login-only preflight；先过 environment gate，再只连接 localhost CDP 并检查登录标记是否存在，不导航页面、不执行内容采集、不写 Validation。

Environment preflight 不读取 Cookie，不运行 CollectorRuntime，不创建 Run，不自动创建或 reserve Budget，不自动修复账号状态；它只读检查显式 Budget 的静态低量上限与当前 `CollectionBudgetUsage` 当日剩余额度，并输出 READY/BLOCKED 与安全原因。

### 5.2 当前离线 CI 基线

M2-D 本轮 offline readiness 代码基线：

- HEAD：`06007c7807bb8413046734dbaf85ff9eafe36475`；
- GitHub Actions：CI #175，run id `31242105740`，completed / success；
- `ruff check .`：success；
- `mypy apps packages`：success，128 source files；
- `pytest`：**240 passed / 1 warning**；
- Alembic：`upgrade head → downgrade -1 → upgrade head → downgrade base → upgrade head` 全部 success；
- Definition sync 第一次：`created=11 / updated=0 / unchanged=0 / failed=0`；
- Definition sync 第二次：`created=0 / updated=0 / unchanged=11 / failed=0`；
- Web：lint / typecheck / unit tests / production build 全部 success。

该 CI 只证明离线工程状态，不产生真实平台访问、真实 Run 或 PASSED Validation。

---

## 6. Search 低量 Gate

pinned upstream 的原始 core 行为：

| 平台 | 原始首屏下限 | M2-D 门槛 | 当前工程状态 |
|---|---:|---:|---|
| B站 | 20 | <=5 | **ENGINEERING READY** |
| 知乎 | 20 | <=5 | **ENGINEERING READY** |
| 微博 | 10 | <=5 | **BLOCKED** |

### 6.1 B站

人工授权的最小 vendored patch：

```text
third_party/MediaCrawler/media_platform/bilibili/core.py
```

语义：

- 不再 `<20 → 20`；
- 使用 client 已支持的 `page_size`；
- `requested_limit=1/3/5` → real client `page_size=1/3/5`；
- `>20` 固定 `page_size=20` 正常有限分页；
- 不修改登录/Cookie/CDP/signature/Risk/proxy/stealth/account。

此前该 patch 已在 CI #151 基线上保持全绿；REAL SMOKE 仍未执行。

### 6.2 知乎

pinned client 已正式存在：

```text
page_size
→ offset=(page-1)*page_size
→ limit=page_size
```

原 core 的问题只是：固定 20、低量上抬到 20，并且没有把 client 已支持的 `page_size` 传入。

因此 M2-D 新增同等级最小 vendored patch：

```text
third_party/MediaCrawler/media_platform/zhihu/core.py
```

语义：

- 不猜测 API 参数；
- 不新增协议；
- `requested_limit=1/3/5` → real client `page_size=1/3/5`；
- `>20` 固定 `page_size=20`；
- page_size 在单次运行内稳定，保持 offset 窗口连续；
- 有限 page count；
- 最后一页只处理剩余 requested items；
- 不修改登录/Cookie/CDP/signature/Risk/proxy/stealth/account。

当前仍属于离线工程验证，REAL SMOKE NOT RUN。

### 6.3 微博

pinned `WeiboClient.get_note_by_keyword` 当前只有 `keyword / page / search_type`；请求参数中没有已实现、已证实的 `page_size / count / limit`。

因此：

```text
WEIBO_LOW_VOLUME_SEARCH = BLOCKED
```

本轮不修改微博 vendored source，不猜测 query 参数、不做接口逆向、不改 Signature。

微博 detail 工程入口存在，但真实 detail 同样未执行。

---

## 7. 首批 Real Smoke Gate

| 平台 | implementation | Low-volume engineering | Real Run ID | REAL SMOKE | Validation |
|---|---|---|---|---|---|
| B站 | `mediacrawler-m2c-v1` | Detail/Search READY | 无 | NOT_TESTED | NOT_TESTED |
| 知乎 | `mediacrawler-m2c-v1` | Detail/Search READY | 无 | NOT_TESTED | NOT_TESTED |
| 微博 | `mediacrawler-m2c-v1` | Detail entry READY；Search BLOCKED | 无 | NOT_TESTED | NOT_TESTED |

当前用户本地真实联调环境尚未配置，因此：

- 不进入真实 B站登录 Gate；
- 不等待人工环境；
- 不自行访问任何平台；
- 不写 PASSED Validation。

详细平台记录：

- `platform-validation/bilibili_m2_validation.md`
- `platform-validation/zhihu_m2_validation.md`
- `platform-validation/weibo_m2_validation.md`

---

## 8. 其他四平台

| 平台 | registered | implemented | fresh-install default | validated |
|---|---:|---:|---:|---|
| 抖音 | yes | yes | disabled | 不因 Fixture/CI 自动 PASSED |
| 小红书 | yes | yes | disabled | 不因 Fixture/CI 自动 PASSED |
| 快手 | yes | yes | disabled | 不因 Fixture/CI 自动 PASSED |
| 百度贴吧 | yes | yes | disabled | 不因 Fixture/CI 自动 PASSED |

---

## 9. M2 最终 Gate

当前只能表述为：

**M2 工程实现接近完成；B站 / 知乎 / 微博真实 Smoke Gate 待人工本地环境完成。**

不能表述为：

```text
M2 完成
```

剩余条件至少包括：

1. 当前离线 readiness batch 的最终 PR HEAD 继续保持完整 CI 全绿；
2. B站真实低量 Detail / Search / Comments / Resume 按 Gate 验证并形成真实 Run evidence；
3. 知乎真实低量验证；
4. 微博在 Search Gate 仍 BLOCKED 的前提下确定最终 M2 验收策略，或未来由有证据的 upstream 能力解除该 Gate；
5. 三平台 Validation 必须依据真实 SUCCEEDED Test/Manual Run，而不是 Fixture/CI；
6. 完成 M2 最终文档收口后，才能评估是否进入 M3。

M3 当前仍未开始。
