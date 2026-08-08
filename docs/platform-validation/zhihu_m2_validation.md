# 知乎 M2 真实验证记录

- 日期：2026-08-08
- 平台：知乎（zhihu）
- pinned MediaCrawler commit：`071c8c0acaece3e82f2532cffb19faeddc9ec1c3`
- implementation_version：`mediacrawler-m2c-v1`
- M2 Engineering：COMPLETE
- REAL SMOKE：NOT_RUN / NOT_TESTED
- Validation：NOT_TESTED
- 账号要求：专用低价值测试账号，与个人/正式业务隔离
- Browser Profile：要求稳定 Profile；本文不记录真实绝对路径
- 网络约束：正常稳定网络，concurrency=1，`--enable_ip_proxy false`

## 当前准备审计

- 登录：pinned 实现支持 qrcode / cookie；手机登录路径当前未完成，不作为 M2-D 路径。
- 登录态标记：`z_c0`；只允许未来 login-only preflight 检查标记是否存在，不记录 Cookie value。
- detail：工程入口存在，未来真实 Smoke 仅使用 1 个由人工指定的普通公开内容。
- search：**ENGINEERING READY，REAL SMOKE NOT_RUN / NOT_TESTED**。
- comments：工程入口存在，未来仅允许 1 个主内容 × 最多 5 条一级评论，subcomments=false。
- creator：pinned CLI 未可靠接通 creator_id，继续保持有效 capability=false，不纳入当前真实 Smoke Gate。
- Profile：专用 Smoke runner 只允许可见 existing CDP，并禁止失败后回退到标准浏览器路径。
- 自动登录：禁用；未预登录时必须停止，不自动扫码、不自动 Cookie 注入。
- 最终离线工程基线：HEAD `54149c4fa83922a270a8fe10eaed4499945ca0e6`，CI #177 success，pytest 240 passed / 1 warning。

## Low-volume Search Gate

pinned `ZhiHuClient.get_note_by_keyword` 已正式支持 `page_size`，并把它用于：

```text
offset = (page - 1) * page_size
limit = page_size
```

原 core 的问题是固定 20、`<20` 时把 `CRAWLER_MAX_NOTES_COUNT` 上抬到 20，并且调用 client 时未传已有的 `page_size`。

M2-D 只对：

```text
third_party/MediaCrawler/media_platform/zhihu/core.py
```

应用最小 compatibility patch：

- `requested_limit=1/3/5` → client `page_size=1/3/5`；
- 不再请求 20 后本地截断；
- `requested_limit>20` 保持稳定 `page_size=20` 正常有限分页；
- page 从 `START_PAGE` 连续推进；
- 最后一页只处理剩余额度；
- 不新增 API 参数，不修改登录/Cookie/CDP/signature/proxy/stealth/Risk/account。

该结论只属于 Engineering / CI 证据，不代表真实知乎接口已验证。

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
Zhihu Engineering Gate: READY
M2 Engineering: COMPLETE
Real Smoke Validation: DEFERRED / NOT_TESTED
Real-world Validation: NOT COMPLETE
```

Real Smoke Deferred 不得改成 PASSED，也不会阻塞 PR #10 合并后的 M3 Engineering。

## Known limitations / future gate

1. 当前没有可用的本地人工真实联调环境，因此登录 / Detail / Search / Comments 均未执行。
2. 未来必须先由人工准备并登录专用测试 Browser Profile；禁止自动扫码、自动 Cookie 注入、自动换号。
3. creator 不属于当前有效能力，不以真实 Smoke 绕过 CLI 边界。
4. 出现 403 / 406 / 429 / CAPTCHA / automation detected / login expired / account restricted / blocked / abnormal 时立即停止，不重试、不换号、不换 Profile、不换代理。
