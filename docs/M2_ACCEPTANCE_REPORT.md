# M2 Acceptance Report

> 当前状态：**M2-D 开发中；B站低量 search 工程 Gate 已通过离线 CI，REAL SMOKE Gate 尚未执行。M2 不能标记为全部完成。**

## 1. 验收语义

本报告严格区分：

- **CI VERIFIED**：Fixture / Mock / PostgreSQL / 静态检查 / Web 工程验证通过；
- **REAL SMOKE VERIFIED**：真实人工低量平台访问完成，并有真实 `SUCCEEDED` Test/Manual Run 与当前 implementation_version 对应的 PASSED Validation。

CI VERIFIED 不能替代 REAL SMOKE VERIFIED。

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

## 5. M2-D 工程准备

开发分支：`feature/m2d-first-platform-validation`

PR：#10 `feat: 完成 M2-D 首批国内平台低量验证`

当前准备内容：

- 首批目标仅 B站 / 知乎 / 微博；
- 专用 Smoke Harness；
- real smoke 仅允许人工 actor + 明确确认；
- CI / Mock / Test 环境禁止 real smoke；
- requested_limit <= 5；
- detail=1；
- comments=1 个主内容 × 最多 5 条一级评论；
- subcomments=false；
- concurrency=1；
- `--enable_ip_proxy false`；
- 单账号每天最多 3 个 Test/Manual smoke Run；
- 必须配置稳定 Browser Profile；
- 仅允许人工准备的可见 CDP 浏览器；
- 禁止自动 qrcode / phone / cookie login；
- CDP 失败后禁止回退到 vendored 标准浏览器路径；
- 抖音 / 小红书 / 快手 / 百度贴吧的新建 Definition 默认 disabled。

### 5.1 Search 低量 Gate

pinned MediaCrawler 原始 search 首屏行为：

| 平台 | pinned search 首屏下限 | M2-D 门槛 | 当前工程状态 |
|---|---:|---:|---|
| B站 | 20 | <=5 | **READY / CI VERIFIED** |
| 知乎 | 20 | <=5 | BLOCKED |
| 微博 | 10 | <=5 | BLOCKED |

B站经人工授权应用了唯一一处 vendored compatibility patch：

`third_party/MediaCrawler/media_platform/bilibili/core.py`

该 patch 仅修改 normal search page-size/pagination：

- 不再把 `<20` 的 `CRAWLER_MAX_NOTES_COUNT` 强制改成 20；
- 单次 search 使用稳定 `page_size=min(20, requested_limit)`；
- requested_limit=1/3/5 时，实际 client 首次 `page_size` 分别为 1/3/5；
- requested_limit>20 时保持 `page_size=20` 的正常分页；
- page/page_size 使用一致窗口，有限页数循环，最后一页只处理剩余条数；
- 未修改登录、Cookie、CDP、签名、风险、代理、stealth、账号状态逻辑；
- pinned upstream commit 未更新。

代码 HEAD `4d31161ade1b962656ab9df653846c2c483d141e` 的 CI #148 已通过：pytest 219 passed / 1 warning，Alembic 全往返、Definition 双同步和 Web 全链路均通过。

知乎与微博仍由 Smoke Harness 在真实 search 前阻断，不通过本地截断结果伪造低量请求。

## 6. 首批 Real Smoke Gate

| 平台 | implementation | Real Run ID | REAL SMOKE | Validation | 当前结论 |
|---|---|---|---|---|---|
| B站 | `mediacrawler-m2c-v1` | 无 | NOT_TESTED | NOT_TESTED | search 工程 Gate READY；待人工账号/Profile下一道 Gate |
| 知乎 | `mediacrawler-m2c-v1` | 无 | NOT_TESTED | NOT_TESTED | 待 search 低量问题与人工账号/Profile处理 |
| 微博 | `mediacrawler-m2c-v1` | 无 | NOT_TESTED | NOT_TESTED | 待 search 低量问题与人工账号/Profile处理 |

详细记录：

- `platform-validation/bilibili_m2_validation.md`
- `platform-validation/zhihu_m2_validation.md`
- `platform-validation/weibo_m2_validation.md`

## 7. 其他四平台

| 平台 | registered | implemented | fresh-install default | validated |
|---|---:|---:|---:|---|
| 抖音 | yes | yes | disabled | 不因 Fixture/CI 自动 PASSED |
| 小红书 | yes | yes | disabled | 不因 Fixture/CI 自动 PASSED |
| 快手 | yes | yes | disabled | 不因 Fixture/CI 自动 PASSED |
| 百度贴吧 | yes | yes | disabled | 不因 Fixture/CI 自动 PASSED |

## 8. M2 最终 Gate

截至当前：

- 工程实现主链：已具备 M2-A / M2-B / M2-C 基线；
- M2-D Smoke Harness：已具备离线安全入口；
- B站 search 低量 compatibility：CI VERIFIED；
- B站 REAL SMOKE：未完成；
- 知乎 REAL SMOKE：未完成；
- 微博 REAL SMOKE：未完成；
- 三个平台真实 PASSED Validation：未完成；
- M3：未开始。

因此当前只能表述为：

**M2 工程实现已进入最后收口阶段，B站已准备进入人工登录前的下一道 Gate；Real Smoke Gate 仍待人工处理，M2 尚未达到全部完成条件。**
