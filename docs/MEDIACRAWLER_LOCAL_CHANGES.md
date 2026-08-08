# MediaCrawler 本地集成变更记录

## 1. 当前上游基线

- Vendored 路径：`third_party/MediaCrawler/`
- 上游仓库：`NanmiCoder/MediaCrawler`
- pinned upstream commit：`071c8c0acaece3e82f2532cffb19faeddc9ec1c3`
- 引入方式：vendored subtree / squash import
- 许可证：`NON-COMMERCIAL LEARNING LICENSE 1.1`

M2-D 不更新 upstream commit，不移除 LICENSE，不改变来源记录。任何真实使用仍必须遵守该许可证与目标平台规则。

状态语义始终是：

```text
registered != implemented != validated
CI VERIFIED != REAL SMOKE VERIFIED
```

Fixture / Mock / CI 不能生成真实 PASSED Validation。

---

## 2. 主系统与 vendored 边界

主系统调用链：

```text
CollectionTask
→ CollectorRuntime
→ MediaCrawlerConnector
→ MediaCrawler Adapter / Resilience
→ dedicated subprocess runner
→ third_party/MediaCrawler
→ JSONL / Result Envelope
→ Platform Mapper
→ RawSignal / CollectedComment
→ Checkpoint / Run / Risk Guard
```

主系统负责：

- Connector Registry / Definition；
- Run 生命周期；
- Collection Budget；
- Risk Guard；
- Account / Browser Profile opaque reference；
- Checkpoint；
- RawSignal / Comment 标准化、幂等与事务；
- Validation Gate；
- 审计与运营状态。

MediaCrawler 仅作为第三方采集执行体。它不拥有主系统数据库事务、Admin Token、Validation 或业务状态。

M2-D Smoke bridge 继续强制：

- `ENABLE_IP_PROXY=False`；
- `MAX_CONCURRENCY_NUM=1`；
- visible browser；
- existing CDP；
- `ENABLE_GET_SUB_COMMENTS=False`；
- 禁止自动 QR / phone / cookie login；
- CDP 失败后禁止回退到标准浏览器路径；
- 不实现代理轮换、账号轮换、验证码绕过、签名破解、stealth 或指纹伪造。

---

## 3. M2-A / M2-B / M2-C vendored 修改历史

### M2-A

M2-A 建立 Versioned Invocation / Result Envelope、受控 subprocess、结果大小限制、脱敏、错误分类等主系统集成边界。

**M2-A 未修改 `third_party/MediaCrawler/` vendored source。**

### M2-B

M2-B 补齐七平台 Mapper、Platform Spec、capabilities、config/ui schema、`CollectedComment`、`raw_signal_comments` 与评论幂等。

**M2-B 未修改 `third_party/MediaCrawler/` vendored source。**

### M2-C

M2-C 增加 Protocol 1.1、Checkpoint / Resume、Incremental、Account / Browser Profile abstraction、SignatureProvider abstraction 与结构化风险输出。

**M2-C 未修改 `third_party/MediaCrawler/` vendored source。**

M2-A/B/C 均未进行真实平台验证来替代 M2-D。

---

## 4. M2-D vendored patch 总表

截至当前 M2-D，vendored source 只有以下两处本地 compatibility patch：

```text
third_party/MediaCrawler/media_platform/bilibili/core.py
third_party/MediaCrawler/media_platform/zhihu/core.py
```

微博及其他平台没有 M2-D vendored patch。

两个 patch 的唯一目标都是：**让主系统 requested_limit 真正约束 search 请求的 page size，而不是平台已经请求较大固定页后再在本地截断。**

两个 patch 均不涉及：

- 登录；
- Cookie 注入；
- Browser Profile / CDP 机制；
- Signature；
- Risk Guard；
- proxy / IP；
- stealth / fingerprint；
- CAPTCHA；
- 账号状态；
- MediaCrawler upstream commit。

---

## 5. B站低量 search page-size compatibility patch

### 5.1 修改文件

```text
third_party/MediaCrawler/media_platform/bilibili/core.py
```

### 5.2 pinned upstream 原行为

B站 normal search 原 core：

- API page size 固定为 20；
- 当 `CRAWLER_MAX_NOTES_COUNT < 20` 时，直接把 limit 上抬为 20；
- 因此 `requested_limit=1~5` 时真实 client 仍发出 `page_size=20`。

Wrapper / Adapter 后置截断只能减少最终处理/保存数量，不能撤销 third-party 已发出的真实请求，所以无法完全解决低量 Gate。

### 5.3 本地最小 patch

- 移除 `<20 → 20` 强制上抬；
- 使用 client 现有正式 `page_size` 参数；
- 单次 normal search 固定 `page_size=min(20, requested_limit)`；
- `requested_limit=1/3/5/20` → client `page_size=1/3/5/20`；
- `requested_limit>20` → 固定 `page_size=20` 正常分页；
- 使用有限 `page_count=ceil(requested_limit/page_size)`；
- page 从 `START_PAGE` 连续递增；
- 最后一页只处理剩余 requested items；
- 服务端短页提前停止。

离线回归测试证明：

```text
requested_limit=5
→ first search client call page_size=5
```

不是 `20 → 本地截断 5`。

### 5.4 subtree pull 检查点

未来同步 upstream 时重点检查：

```text
third_party/MediaCrawler/media_platform/bilibili/core.py
BilibiliCrawler.search_by_keywords
```

如果 upstream 已原生支持同等低量语义，应优先删除本地 patch；发生冲突时必须重新验证 `START_PAGE`、page/page_size 窗口、末页和 requested limit，不得机械覆盖。

---

## 6. 知乎低量 search page-size compatibility patch

### 6.1 修改文件

```text
third_party/MediaCrawler/media_platform/zhihu/core.py
```

### 6.2 pinned client 已有正式能力

pinned `ZhiHuClient.get_note_by_keyword` 已明确声明：

```text
page_size: int = 20
```

并在现有请求参数构造中正式使用：

```text
offset = (page - 1) * page_size
limit = page_size
```

因此本次不猜测 API 参数、不新增平台协议、不修改签名逻辑。

### 6.3 pinned core 为什么仍固定 20

原 `ZhihuCrawler.search`：

- core 自己定义固定页大小 20；
- 当 `CRAWLER_MAX_NOTES_COUNT < 20` 时把 limit 强制上抬到 20；
- 调用 `get_note_by_keyword(keyword=..., page=...)` 时没有把 client 已支持的 `page_size` 传进去；
- client 因而继续使用默认 `page_size=20`。

与 B站一样，仅在 Wrapper 截断结果不能减少已经发生的真实请求规模，因此需要 core 层的最小 compatibility patch。

### 6.4 本地最小 patch

- 移除 `<20 → 20` 的 `CRAWLER_MAX_NOTES_COUNT` 强制上抬；
- 继续使用 client 已正式存在的 `page_size` 参数；
- 单次 normal search 固定 `page_size=min(20, requested_limit)`；
- `requested_limit=1/3/5/20` → client `page_size=1/3/5/20`；
- `requested_limit>20` → 固定 `page_size=20`；
- `page_count=ceil(requested_limit/page_size)`，有限循环；
- page 从 `START_PAGE` 连续递增；
- 因 `offset=(page-1)*page_size`，单次运行 page_size 不变化，避免 offset 窗口重叠/回跳；
- 最后一页只处理剩余 requested items；
- 短页提前停止。

离线回归覆盖：

- requested_limit=1；
- 3；
- 5；
- 20；
- 21；
- 45；
- START_PAGE + page_size 窗口；
- 多页不重复；
- 有限页数；
- client source 的 `page_size → offset/limit` 显式映射。

关键语义：

```text
requested_limit=5
→ first Zhihu search client call page_size=5
```

### 6.5 subtree pull 检查点

未来同步 upstream 时重点检查：

```text
third_party/MediaCrawler/media_platform/zhihu/core.py
ZhihuCrawler.search
third_party/MediaCrawler/media_platform/zhihu/client.py
ZhiHuClient.get_note_by_keyword
```

必须重新确认 client 的 `page_size`、`offset`、`limit` 语义是否变化。若 upstream 原生修复，应删除本地 patch；不得为了保留 patch 猜测新 API 参数。

---

## 7. 微博低量 Search Gate：保持 BLOCKED

### 7.1 pinned source 审计

pinned `WeiboClient.get_note_by_keyword` 当前明确参数只有：

- `keyword`；
- `page`；
- `search_type`。

当前请求参数构造包含 `containerid`、`page_type`、`page`，**没有已经实现或被 pinned source 证明的 `page_size` / `count` / `limit` 参数**。

pinned core 则以 10 作为 search 页大小下限，并会把较小 `CRAWLER_MAX_NOTES_COUNT` 上抬到 10。

### 7.2 为什么不 patch

若要把微博 search 的真实单页请求从约 10 降到 `<=5`，当前 pinned source 没有证据表明存在可直接使用的小 page-size 参数。

因此 M2-D 明确不做：

- 参数猜测；
- 未文档化 query 参数试探；
- 接口逆向；
- Signature 修改；
- 风控绕过。

当前状态保持：

```text
WEIBO_LOW_VOLUME_SEARCH = BLOCKED
```

微博 detail 的 pinned 入口存在，但真实 detail 仍未运行；入口存在不等于 Validation PASSED。

未来只有在 upstream 明确实现或已有 pinned client 明确暴露合法低量参数后，才重新评估 Search Gate。

---

## 8. Validation 与真实联网边界

本文件记录的是工程实现，不是平台实跑结果。

当前三平台仍为：

```text
B站   REAL SMOKE = NOT_TESTED / Validation = NOT_TESTED
知乎   REAL SMOKE = NOT_TESTED / Validation = NOT_TESTED
微博   REAL SMOKE = NOT_TESTED / Validation = NOT_TESTED
```

M2-D offline readiness 不执行登录、扫码、Cookie 注入或真实内容请求。
