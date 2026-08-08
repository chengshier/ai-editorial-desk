# B站 M2 真实验证记录

- 日期：2026-08-08
- 平台：B站（bilibili）
- pinned MediaCrawler commit：`071c8c0acaece3e82f2532cffb19faeddc9ec1c3`
- implementation_version：`mediacrawler-m2c-v1`
- M2 Engineering：COMPLETE
- REAL SMOKE：NOT_RUN / NOT_TESTED
- Validation：NOT_TESTED
- 账号要求：专用低价值测试账号，与个人/正式业务隔离
- Browser Profile：要求稳定 Profile；本文不记录真实绝对路径
- 网络：正常稳定网络，concurrency=1，`--enable_ip_proxy false`

## 当前准备审计

- 登录：pinned 实现支持 qrcode / cookie；真实 Smoke 阶段仍只允许人工登录专用低价值测试 Profile，不做自动扫码或 Cookie 注入。
- 登录态标记：`SESSDATA` / `DedeUserID`；验证文档不记录实际 Cookie 值。
- detail：工程入口存在，未来真实 Smoke 仅使用 1 个普通公开内容。
- search：**ENGINEERING READY，REAL SMOKE NOT_RUN / NOT_TESTED**。经人工授权，仅对 `third_party/MediaCrawler/media_platform/bilibili/core.py` 应用了最小 page-size compatibility patch；`requested_limit=1~5` 时真实 client `page_size` 同步为 1~5，不再先请求 20 条再截断。
- search >20：保持单次运行稳定 `page_size=20`，正常有限分页；末页只处理剩余数量。
- comments：工程入口存在，未来仅允许 1 个主内容 × 最多 5 条一级评论，subcomments=false。
- Profile：专用 Smoke runner 只允许可见 existing CDP，并禁止失败后回退到标准浏览器路径。
- 自动登录：禁用；未预登录时应返回 `AUTH_REQUIRED` 并停止。
- 最终离线工程基线：HEAD `54149c4fa83922a270a8fe10eaed4499945ca0e6`，CI #177 success，pytest 240 passed / 1 warning。

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
Bilibili Engineering Gate: READY
M2 Engineering: COMPLETE
Real Smoke Validation: DEFERRED / NOT_TESTED
Real-world Validation: NOT COMPLETE
```

Real Smoke Deferred 不得改成 PASSED，也不会阻塞 PR #10 合并后的 M3 Engineering。

## Known limitations / future gate

1. B站 search 的固定 20 条工程阻断已通过最小本地 compatibility patch 解除，但只属于 CI/Engineering 证据，不是 REAL SMOKE VERIFIED。
2. 未来必须先由人工准备并登录专用测试 Browser Profile；禁止自动扫码、自动 Cookie 注入、自动换号。
3. 真实执行顺序仍建议 Detail=1 → Search<=5 → Comments<=5 → Resume，一次只验证一个平台。
4. 出现 403 / 406 / 429 / CAPTCHA / automation detected / login expired / account restricted / blocked / abnormal 时立即停止，不重试、不换号、不换 Profile、不换代理。
