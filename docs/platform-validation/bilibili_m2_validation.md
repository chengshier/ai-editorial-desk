# B站 M2 真实验证记录

- 日期：2026-08-07
- 平台：B站（bilibili）
- pinned MediaCrawler commit：`071c8c0acaece3e82f2532cffb19faeddc9ec1c3`
- implementation_version：`mediacrawler-m2c-v1`
- 环境：本地人工真实 Smoke，尚未执行
- 账号要求：专用低价值测试账号，与个人/正式业务隔离
- Browser Profile：要求稳定 Profile；本文不记录真实绝对路径
- 网络：正常稳定网络，concurrency=1，`--enable_ip_proxy false`

## 当前准备审计

- 登录：pinned 实现支持 qrcode / cookie；手机登录路径不可依赖。
- 登录态标记：`SESSDATA` / `DedeUserID`，验证文档不记录实际 Cookie 值。
- detail：CLI 路径存在，可计划使用 1 个普通公开内容。
- search：**工程低量 Gate 已 READY，但尚未真实执行**。经人工授权，仅对 `third_party/MediaCrawler/media_platform/bilibili/core.py` 应用了最小 page-size compatibility patch；`requested_limit=1~5` 时真实 client `page_size` 同步为 1~5，不再先请求 20 条再截断。
- search >20：保持单次运行稳定 `page_size=20`，按 `page + page_size` 正常分页；末页只处理剩余数量，页数使用有限计算，避免重复页和无限循环。
- comments：CLI 路径存在，后续仅允许 1 个主内容 × 最多 5 条一级评论，subcomments=false。
- Profile：专用 Smoke runner 只允许可见 CDP，并禁止失败后回退到标准浏览器路径。
- 自动登录：禁用；未预登录时应返回 `AUTH_REQUIRED` 并停止。
- 离线验收：B站低量分页回归测试已进入 CI；代码 HEAD `4d31161ade1b962656ab9df653846c2c483d141e` 对应 CI #148 success，pytest 219 passed / 1 warning。

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

1. B站 search 的固定 20 条工程阻断已通过最小本地兼容 patch 解除，但这只属于 **CI VERIFIED**，不是 REAL SMOKE VERIFIED。
2. 必须先由人工准备并登录专用测试 Browser Profile；禁止自动扫码、自动 Cookie 注入、自动换号。
3. 首次真实执行仍按 Detail=1 → Search<=5 → Comments<=5 → Resume 的顺序逐步进行，一次只验证 B站。
4. 出现 403 / 406 / 429 / CAPTCHA / automation detected / login expired / account restricted 或 abnormal 时立即停止，不重试、不换号、不换代理。
