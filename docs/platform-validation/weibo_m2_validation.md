# 微博 M2 真实验证记录

- 日期：2026-08-08
- 平台：微博（weibo）
- pinned MediaCrawler commit：`071c8c0acaece3e82f2532cffb19faeddc9ec1c3`
- implementation_version：`mediacrawler-m2c-v1`
- 当前环境：仅离线工程 readiness；人工真实 Smoke 尚未执行
- 账号要求：专用低价值测试账号，与个人/正式业务隔离
- Browser Profile：要求稳定 Profile；本文不记录真实绝对路径
- 网络约束：正常稳定网络，concurrency=1，`--enable_ip_proxy false`

## 当前准备审计

- 登录：pinned 实现支持 qrcode / cookie；手机登录路径不可依赖。
- 登录态标记：`SSOLoginState` / `WBPSESS`；只允许后续 login-only preflight 检查标记是否存在，不记录 Cookie value。
- detail：pinned client/core 存在指定内容详情入口，但尚未真实执行。
- search：**WEIBO_LOW_VOLUME_SEARCH = BLOCKED**。
- comments：入口存在，真实验证后续仍必须限定 1 个主内容 × 最多 5 条一级评论，subcomments=false。
- Profile：专用 Smoke runner 只允许可见 existing CDP，并禁止失败后回退到标准浏览器路径。
- 自动登录：禁用；未预登录时必须停止，不自动扫码、不自动 Cookie 注入。

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

core 当前则以约 10 条作为 search 页大小下限，并会把较小 `CRAWLER_MAX_NOTES_COUNT` 上抬到 10。

因此当前无法像 B站/知乎一样，通过“把 core 已有 limit 传给 client 已有 page_size”来证明真实请求量 `<=5`。

M2-D 明确不做：

- 未文档化参数猜测；
- API query 参数试探；
- 接口逆向；
- Signature 修改；
- 登录/Cookie/风控逻辑修改；
- 403/406/429 绕过。

本轮**没有修改任何微博 vendored source**。

只有未来 upstream 或当前 pinned client 明确出现可证实的小 page-size/count/limit 能力时，才重新评估微博 Search Gate。

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
| result | REAL SMOKE 未开始 |

## Known limitations

1. 微博 low-volume search 仍为 BLOCKED；不得为了完成 M2-D 猜测 API 参数。
2. detail 工程入口存在不等于真实平台通过；当前 REAL SMOKE 仍为 NOT_TESTED。
3. 当前没有可用的本地人工真实联调环境，禁止自行联网验证。
4. 必须先由人工准备并登录专用测试 Browser Profile；禁止自动扫码、自动 Cookie 注入、自动换号。
5. 出现 403 / 406 / 429 / CAPTCHA / automation detected / login expired / account restricted / blocked / abnormal 时立即停止，不重试、不换号、不换 Profile、不换代理。
