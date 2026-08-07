# 知乎 M2 真实验证记录

- 日期：2026-08-07
- 平台：知乎（zhihu）
- pinned MediaCrawler commit：`071c8c0acaece3e82f2532cffb19faeddc9ec1c3`
- implementation_version：`mediacrawler-m2c-v1`
- 环境：本地人工真实 Smoke，尚未执行
- 账号要求：专用低价值测试账号，与个人/正式业务隔离
- Browser Profile：要求稳定 Profile；本文不记录真实绝对路径
- 网络：正常稳定网络，concurrency=1，`--enable_ip_proxy false`

## 当前准备审计

- 登录：pinned 实现支持 qrcode / cookie；手机登录路径当前未完成，不作为 M2-D 路径。
- 登录态标记：`z_c0`，验证文档不记录实际 Cookie 值。
- detail：CLI 路径存在，可计划使用 1 个普通公开内容。
- search：**当前阻断**。pinned core 将首屏结果下限强制为 20，高于 M2-D `<=5` 的真实低量门槛。
- comments：CLI 路径存在，后续仅允许 1 个主内容 × 最多 5 条一级评论，subcomments=false。
- creator：pinned CLI 未可靠接通 creator_id，继续保持有效 capability=false，不纳入 M2-D Smoke。
- Profile：专用 Smoke runner 只允许可见 CDP，并禁止失败后回退到标准浏览器路径。
- 自动登录：禁用；未预登录时应返回 `AUTH_REQUIRED` 并停止。

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

1. search 固定首屏 20 条的 pinned 行为尚未满足 M2-D 低量门槛；在解决前禁止真实 search。
2. 必须先由人工准备并登录专用测试 Browser Profile；禁止自动扫码、自动 Cookie 注入、自动换号。
3. creator 不属于当前有效能力，不以真实 Smoke 绕过 CLI 边界。
4. 出现 403 / 406 / 429 / CAPTCHA / automation detected / login expired / account restricted 或 abnormal 时立即停止，不重试、不换号、不换代理。
