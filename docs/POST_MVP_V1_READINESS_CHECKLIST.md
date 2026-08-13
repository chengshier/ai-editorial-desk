# POST-MVP / V1 Readiness Checklist

> Status: ACTIVE
>
> 本文用于 M5 MVP 收口完成后的 Post-MVP / V1 readiness 管理。它不是新的 Milestone，不创建 M6，也不改变既有 M0→M5 历史阶段语义。

## 1. 正式路线

正式路线继续遵循：

```text
M0
→ M1
→ M2
→ M3
→ M4
→ M5
→ V1-A / V1-B / V1-C / V1-D
→ V1.5
→ V2
→ P1
→ P2
```

不存在 M6。

V1 四条支线允许部分并行，但必须在 MVP 主闭环稳定后开始；实现仍按独立小批次推进，不一次开启多个高风险开发任务。

## 2. MVP Closeout Baseline

截至 2026-08-13：

- M5-A Editorial Workbench = COMPLETE / MERGED；
- M5-B Daily Candidates / Editorial Workflow = COMPLETE / MERGED；
- M5-C Publication / Performance Feedback = COMPLETE / MERGED；
- M5-D A Engineering Hardening = PASS；
- M5-D B Real Platform Smoke = PASS；
- M5-D C Production AI Provider = PASS；
- M5-D D Full Human-in-loop MVP E2E = PASS；
- formal `verify_m5d_e2e = PASS`；
- PR #23 `feat: 完成 M5-D Hardening与MVP收口` = MERGED；
- PR #23 merge commit = `8ab9200172786705f9e73093646e3d3d3507ee2f`；
- PR #25 `docs: 建立Post-MVP与V1 readiness基线` = MERGED；
- Post-MVP 文档收口后的 immutable MVP release baseline target = `8b0e1a4ce4fdf2ae1eb01cd0faf76dd47d31dacb`；
- baseline exact-head GitHub Actions `python` = success；
- baseline exact-head GitHub Actions `web` = success；
- M5-D Real Validation Report = PASS；
- M5 Overall = COMPLETE。

后续功能 commit 不改变上述 immutable MVP release baseline target。

M5-D 真实验证链：

```text
Real Collection
→ RawSignal
→ Event
→ Evidence Extraction
→ Human Claim Verification
→ Trend
→ Production Editorial Scoring
→ Candidate
→ Human Adopt
→ Card / Pack
→ Production AI Draft
```

Production Provider：

```text
provider = deepseek-production
model = deepseek-v4-flash
```

## 3. M2 Deferred Real-Smoke 的后续语义

M2 历史 Acceptance 保持原始事实：

```text
M2 Engineering = COMPLETE
M2 Real Smoke Validation = DEFERRED / NOT_TESTED（当时状态）
M2 Real-world Validation = NOT COMPLETE（当时状态）
```

Post-MVP 不重写该历史验收记录。

根据后续 D-030 与 M5-D 真实验证：

```text
M2 deferred real-smoke Gate for MVP/M5 closeout
= SATISFIED / CLOSED by Bilibili low-volume real smoke
```

当前正式证明范围仅为 Bilibili low-volume real smoke。不得扩大为七个平台均已 production validated。

平台 coverage 当前语义：

| 平台 | 单独 real smoke evidence | 当前处理 |
|---|---|---|
| Bilibili | YES | 已完成，不重复无意义 smoke |
| Zhihu | NO | Post-MVP 非阻塞 coverage follow-up |
| Weibo | NO | 保留 low-volume search known limitation；仅允许已证实安全能力 |
| Douyin | NO | V1-A 逐平台灰度 |
| Xiaohongshu | NO | V1-A 逐平台灰度 |
| Kuaishou | NO | V1-A 逐平台灰度 |
| Baidu Tieba | NO | V1-A 逐平台灰度 |

## 4. Platform Risk Boundary

任何真实平台验证继续遵守：

- isolated low-value test account；
- visible Chrome/CDP；
- stable controlled browser profile；
- concurrency=1；
- low-volume；
- 不破解 CAPTCHA；
- 不做 fingerprint spoofing；
- 不在 restriction 后自动换号；
- 不做 proxy rotation 绕过；
- 403 / 406 / 429 / CAPTCHA / automation detected / account restricted / abnormal / login invalidation 等立即停止转人工；
- Bilibili 已完成 MVP real smoke，不为追求“全平台 PASS”重复增加风险；
- Weibo 不猜测未证实 API 参数、不扩大请求量。

## 5. Post-MVP Backlog Priority

| # | Work Item | Priority | 目标 | Real Platform | Paid AI | 主要风险 | Completion Standard |
|---|---|---|---|---|---|---|---|
| 1 | MVP Baseline / Release Hygiene | NOW | 固化 M5 最终事实与 V1 baseline | NO | NO | 错改历史验收 | 状态文档一致；形成 checklist；明确 immutable baseline；准备 tag/release |
| 2 | AI Generation Policy v1 | NOW | Evidence/Scoring/Draft generation 参数按 task 配置，不再为 token 调参改业务代码 | NO | 开发验收 NO | 配置优先级混乱、绕过 Budget、破坏现有 contract | task-level DB/Admin config + version/audit + code fallback；AI Budget/Risk/strict JSON contract 不变 |
| 3 | P1-lite Operability Baseline | NEXT | V1 扩平台前建立最低长期运行保障 | NO | NO | 过早演变成全面 P1 重构 | backup/restore、disk/backlog/provider failure/risk/checkpoint/budget 基础观测；7-day soak checklist |
| 4 | V1-A Single-platform Gray Rollout | NEXT | 抖音/小红书/快手/贴吧逐平台灰度 | YES | NO | 平台风控 | 一次仅启一个；其他保持 disabled；成功或安全 BLOCK 均有证据 |
| 5 | V1-B Lifecycle / Trend Semantics | NEXT | 明确跨天事件、旧闻再发酵、官方回应和默认窗口 | NO | NO | lifecycle 抖动、窗口语义不一致 | emerging/growing/stable/declining/resolved 语义冻结并有 deterministic regression |
| 6 | M2 Coverage Follow-up | NEXT / NON-BLOCKING | 补 Zhihu 与 Weibo 的独立 coverage knowledge | YES | NO | 账号/平台限制 | Zhihu 受控 low-volume；Weibo 仅安全已证实 capability；PASS 或安全 BLOCK 均记录 |
| 7 | V1-C Selective Multimedia | LATER | 字幕优先、ASR、关键帧、OCR、有限视觉理解 | 按需 | 可能 | 成本/延迟/存储/错误传播 | TOP20 ASR / TOP10 frame / TOP5 vision；时间码/provenance；失败不阻断文本主链 |
| 8 | V1-D Real Feedback & Calibration | LATER | 在 M5-C 现有 Publication/Performance 模型上形成运营校准闭环 | 最终需要真实数据 | 非必须 | 指标口径、反馈偏差 | 有真实样本；采用率/来源命中/score correlation；生成校准建议但不自动改权重/Prompt |

## 6. 明确 NOT NEEDED / 禁止回退

以下事项不进入 Post-MVP backlog：

- 创建 M6；
- 重新打开 M5-D；
- 重新把 M2 deferred Gate 当 blocker；
- 重复 Bilibili real smoke；
- 为“全平台 PASS”强测 Weibo；
- 建立粗暴全局 `AI_MAX_TOKENS`；
- 为兼容模型增加 malformed JSON repair parser；
- 重新拆成两套 Editorial Scoring risk semantics；
- 重建 M5-C Publication / Performance 数据模型；
- 现在直接全面 Redis / Worker 重构。

## 7. AI Generation Policy v1 Scope

这是 Baseline 收口后的第一项真正业务开发任务。

### 7.1 第一版目标

优先只解决已经在 M5-D 暴露并真实发生的问题：

```text
evidence_extraction.max_output_tokens
editorial_scoring.max_output_tokens
draft_generation.max_output_tokens
```

现有 fallback 保持：

```text
evidence_extraction = 4096
editorial_scoring = 4096
draft_generation = 6000
```

### 7.2 设计原则

优先复用现有 versioned `AITaskRouteRecord` / route config，不无理由建立第二套 task routing truth。

目标解析顺序：

```text
active task route generation config
→ typed policy resolver
→ code fallback
→ existing AIGateway
→ existing AI Budget reservation / settlement
→ Provider
```

要求：

- task-level config；
- DB / Admin UI；
- versioning；
- audit；
- typed validation；
- code constant 仅 fallback；
- 不能绕过 AI Budget；
- `allowed_risk_levels` shared semantics 不改变；
- `draft-generation-v2` exactly-one-JSON strict contract 不改变；
- 通用 parser 继续严格 `json.loads`；
- 第一版不顺手重构整个 AI 参数中心。

未来可逐步扩展：

```text
temperature
timeout
retry policy
other generation parameters
```

但必须逐项评估与现有 Provider / Route / Budget ownership 的关系，避免重复配置真相。

### 7.3 当前实现进度

当前开发分支：

```text
feature/ai-generation-policy-config
```

PR：

```text
#26 feat: 增加任务级AI生成策略配置
```

已实现：

- 新增 typed generation policy resolver；
- `AITaskRouteRecord.config.generation_policy.max_output_tokens` 优先于调用方 fallback；
- effective token 同时用于 Provider request、normalized input/hash 与 AI Budget reservation；
- Admin Route schema 拒绝非对象、布尔值、非整数、0 与负数；
- AI Route 页面仅对 Evidence / Editorial Scoring / Draft 暴露 typed 数字输入；
- 空值保持代码 fallback 4096 / 4096 / 6000；
- 保存保留 unrelated route config，并继续创建新的 Route version / Audit Log；
- 新增 runtime、Provider request、Budget gate、invalid config 与 Web save payload 回归。

本批：

```text
NO NEW MIGRATION
NO REAL PLATFORM REQUEST
NO PAID AI
NO PRODUCTION DB CHANGE
```

PR #26 在人工合并前保持 `IN_PROGRESS / ENGINEERING VALIDATION`；CI 全绿后只能提升为 Engineering PASS，仍不自动 merge。

## 8. P1-lite Scope Boundary

P1-lite 是 Post-MVP/V1 readiness 横切保障，不提前宣称进入正式 P1。

优先评估：

- 7-day soak；
- 后续 30-day soak；
- DB backup / restore drill；
- disk usage；
- task backlog；
- Provider failure rate；
- platform risk events；
- checkpoint recovery；
- AI / collection budget alerts；
- basic operability runbook。

完整 Redis、Worker 并发、任务优先级、灾难恢复体系仍属于正式 P1，不在 readiness 阶段无边界扩张。

## 9. Release Baseline Strategy

Post-MVP readiness 文档已经由 PR #25 合并到 main。immutable MVP release baseline target 冻结为：

```text
8b0e1a4ce4fdf2ae1eb01cd0faf76dd47d31dacb
```

推荐：

```text
Git tag: mvp-closeout-2026-08-13
GitHub Release: MVP Closeout — M5-D PASS
```

不建议在 V1 尚未完成时直接使用 `v1.0.0` 表示正式 V1。

当前执行环境的 GitHub connector 没有 create Tag / create Release 写动作，因此本步骤标记为 `TOOLING_BLOCKED`，不使用 branch 冒充 Tag，也不把后续功能 SHA 当成 MVP baseline。待具备 Tag/Release 写能力时必须仍指向上述 exact baseline SHA。

真实验证报告中的 validation engineering HEAD / invocation / artifact provenance 保持原值，不因 release tag 改写。

## 10. Execution Order

```text
1. Post-MVP readiness / 文档 / baseline 收口
2. 建立 MVP Git tag / GitHub Release
3. AI Generation Policy v1
4. P1-lite 最低 operability
5. V1-A 单平台灰度
6. V1-B Lifecycle / Trend
7. V1-C Multimedia
8. V1-D Feedback / Calibration
```

第 2 步因当前工具写能力受限已冻结 exact target，不阻塞不依赖 Tag 的第 3 步工程开发；未来补 Tag/Release 时不得改 target。

M2 Zhihu / Weibo coverage follow-up 是非阻塞旁路线，插入安全窗口执行，不把项目拖回 M2。

## 11. Progress Tracker

| Item | Status | Notes |
|---|---|---|
| Post-MVP/V1 readiness audit | COMPLETE | 2026-08-13；M5 工程/真实验证 PASS，正式路线与后续 backlog 已冻结 |
| Create readiness baseline branch | COMPLETE | `chore/post-mvp-v1-readiness-baseline` |
| Add this checklist | COMPLETE | `docs/POST_MVP_V1_READINESS_CHECKLIST.md` |
| Sync START_HERE post-merge status | COMPLETE | 已切换到 M5 COMPLETE / Post-MVP/V1 readiness |
| Sync M5 Acceptance final status | COMPLETE | 已记录 M5-D A/B/C/D PASS 与 M5 Overall COMPLETE |
| Sync M5-D Report post-merge note | COMPLETE | 保留 validation provenance，并补 PR #23 merge note |
| Add final CHANGELOG closeout entry | COMPLETE | 已有 2026-08-13 MVP closeout / Post-MVP entry；历史记录保持不改 |
| Confirm docs consistency | COMPLETE | 正式路线、M2/M5-D 语义与入口文档已核对 |
| Baseline documentation PR | COMPLETE / MERGED | PR #25 已人工合并 |
| Immutable MVP baseline target | COMPLETE / FROZEN | `8b0e1a4ce4fdf2ae1eb01cd0faf76dd47d31dacb`；Python/Web baseline CI success |
| MVP tag / GitHub Release | TOOLING_BLOCKED | 推荐 tag/release 已冻结；当前 connector 无创建写动作，不伪造完成状态 |
| AI Generation Policy v1 | IN_PROGRESS / PR #26 OPEN | 功能、Admin UI、typed validation 与回归已提交；等待 exact-head CI 与人工 merge |
| P1-lite | PENDING | PR #26 合并后从最新 main 单独建分支 |
| V1-A | PENDING | P1-lite 最低 operability 后按单平台灰度推进 |

## 12. Change Discipline

后续每个开发批次继续遵守：

- 从最新 main 新建独立分支；
- 不从旧 feature branch 继续派生；
- 一个批次解决一个明确问题；
- 不自动合并 PR；
- 真实平台与付费 AI 仅在明确需要且人工确认的验证阶段执行；
- Risk / Budget / Evidence / provenance guard 不为测试便利而绕过；
- 完成后更新本 checklist 的 progress tracker 与 CHANGELOG。
