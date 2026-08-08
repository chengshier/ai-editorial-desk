# 微博 M2 真实验证记录

- 日期：2026-08-08
- 平台：微博（weibo）
- pinned MediaCrawler commit：`071c8c0acaece3e82f2532cffb19faeddc9ec1c3`
- implementation_version：`mediacrawler-m2c-v1`
- M2 Engineering：COMPLETE（含已知限制接受）
- REAL SMOKE：NOT_RUN / NOT_TESTED
- Validation：NOT_TESTED
- LOW_VOLUME_SEARCH：BLOCKED / ACCEPTED KNOWN LIMITATION
- 账号要求：专用低价值测试账号，与个人/正式业务隔离
- Browser Profile：要求稳定 Profile；本文不记录真实绝对路径
- 网络约束：正常稳定网络，concurrency=1，`--enable_ip_proxy false`

## 当前准备审计

- 登录：pinned 实现支持 qrcode / cookie；手机登录路径不可依赖。
- 登录态标记：`SSOLoginState` / `WBPSESS`；只允许未来 login-only preflight 检查标记是否存在，不记录 Cookie value。
- detail：pinned client/core 存在指定内容详情工程入口，但尚未真实执行。
- search：**WEIBO_LOW_VOLUME_SEARCH = BLOCKED / ACCEPTED KNOWN LIMITATION**。
- comments：工程入口存在，未来真实验证仍必须限定 1 个主内容 × 最多 5 条一级评论，subcomments=false。
- Profile：专用 Smoke runner 只允许可见 existing CDP，并禁止失败后回退到标准浏览器路径。
- 自动登录：禁用；未预登录时必须停止，不自动扫码、不自动 Cookie 注入。
- 最终离线工程基线：HEAD `54149c4fa83922a270a8fe10eaed4499945ca0e6`，CI #177 success，pytest 240 passed / 1 warning。

## Low-volume Search Gate 审计

pinned `WeiboClient.get_note_by_keyword` 当前明确暴露：

- `keyword`；
- `page`；
- `search_type`。

当前请求参数构造包含：

- `containerid`；
- `page_type`；
- `page`。

**pinned source 中没有已实现、已证实的 `page_size` / `count` / `limit` 参数。**

core 当前以约 10 条作为 search 页大小下限，并会把较小 `CRAWLER_MAX_NOTES_COUNT` 上抬到 10。因此无法像 B站/知乎一样，通过“把 core 的 requested limit 传给 client 已有低量参数”来证明真实请求量 `<=5`。

正式处理：

```text
WEIBO_LOW_VOLUME_SEARCH = BLOCKED
ACCEPTED KNOWN LIMITATION
```

接受原因：

- 不猜未文档化 API 参数；
- 不做 query 参数试探或接口逆向；
- 不修改/扩展 Signature；
- 不修改登录/Cookie/风控逻辑；
- 不通过请求 10 条再本地截断伪造 `<=5`；
- 不为完成 Gate 绕过请求量限制。

本轮及当前工程基线**没有修改任何微博 vendored source**。

只有以下任一条件成立时才重新打开微博 Search Gate：

1. upstream 明确提供低量参数；
2. 新 pinned version 有可验证实现；
3. 有正规源码证据表明现有接口支持低量请求。

该 Accepted Known Limitation 不再阻塞 M3 Engineering。

## Real Smoke Evidence

| 字段 | 当前值 |
|---|---|
| mode | NOT_RUN |
| requested_limit | 0 |
| collected | 0 |
| inserted | 0 |
| duplicates | 0 |
| comments | 0 |
| checkpoint | NOT_RUN |
| risk events | 0 |
| Validation Run ID | 无 |
| Validation status | NOT_TESTED |
| result | REAL SMOKE NOT_RUN / NOT_TESTED |

## 阶段结论

```text
Weibo Detail Engineering Entry: READY
Weibo Low-volume Search: BLOCKED / ACCEPTED KNOWN LIMITATION
M2 Engineering: COMPLETE
Real Smoke Validation: DEFERRED / NOT_TESTED
Real-world Validation: NOT COMPLETE
```

Real Smoke Deferred 不得改成 PASSED，也不会阻塞 PR #10 合并后的 M3 Engineering。

## Known limitations / future gate

1. 微博 low-volume search 维持 BLOCKED，不再为完成 M2-D 继续研究或猜测 API 参数。
2. Detail 工程入口存在不等于真实平台通过；当前 REAL SMOKE 仍为 NOT_TESTED。
3. 当前没有可用的本地人工真实联调环境，禁止自行联网验证。
4. 未来必须先由人工准备并登录专用测试 Browser Profile；禁止自动扫码、自动 Cookie 注入、自动换号。
5. 出现 403 / 406 / 429 / CAPTCHA / automation detected / login expired / account restricted / blocked / abnormal 时立即停止，不重试、不换号、不换 Profile、不换代理。
