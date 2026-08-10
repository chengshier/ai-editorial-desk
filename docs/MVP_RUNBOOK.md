# AI 编辑部 MVP 运行与真实验证手册

> M5-D Phase 1 Engineering Hardening Runbook
>
> 本手册不会自动登录平台、不会自动发布、不会绕过 Risk/Budget，也不会把 CI/Mock 结果写成真实验证 PASS。

## 1. MVP 状态边界

MVP 收口必须分别检查四类证据：

1. Engineering Hardening：代码、Harness、PostgreSQL、Web、Alembic、CI。
2. Real Platform Smoke：受控本地真实网络 + 可见 Chrome/CDP + 隔离低价值测试账号。
3. Production AI Provider Validation：真实 `env://...` credential + 真实网络 + AIGateway 正式业务 Invocation。
4. Full Human-in-loop MVP E2E：真实 RawSignal 到 Human Adopt、Card/Pack、真实 AI Draft 的同链 provenance。

任一真实 Gate 未通过时，`M5 Overall` 必须继续 `NOT COMPLETE`。

## 2. 启动顺序

### 2.1 PostgreSQL

按仓库现有 Docker/PostgreSQL 方式启动数据库。确认数据库可访问后再执行 migration。

### 2.2 Alembic

```bash
alembic upgrade head
```

M5-D 不新增 migration，预期 head：

```text
20260810_0015
```

### 2.3 Connector Definitions

执行仓库现有 Definition Sync，两次执行中的第二次必须满足：

```text
created=0
updated=0
failed=0
```

### 2.4 API

按现有配置启动 FastAPI。Admin Token 与 Actor 仍使用现有机制，不写入本手册、Git、URL 或 shell 示例。

### 2.5 Web

```bash
cd apps/web
npm install
npm run dev
```

生产构建验证：

```bash
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

## 3. Connector / Account / Profile

真实平台验证只使用隔离、低价值测试账号，不使用个人主账号或正式发布账号。

必须满足：

- Connector Definition 与 Instance enabled；
- Bilibili 或 Zhihu search capability 可用；
- Source enabled/active；
- PlatformAccount 属于目标 Connector/platform；
- Account 为 `HEALTHY`；
- `manual_review_required=false`；
- 无 active cooldown；
- 使用已有受控 browser profile reference；
- 不自动登录、不自动扫码；
- 不创建代理轮换、账号轮换、fingerprint spoofing 或 CAPTCHA 处理。

Profile 只在本地受控运行环境解析。报告只保留脱敏 reference，不记录绝对路径。

## 4. Collection Budget

真实 Smoke 前必须存在显式 Collection Budget。M5-D Preflight 不会自动创建默认预算。

MVP real smoke 使用更严格的 M2 gate：

- search requested limit：默认 `1`，绝不超过 `5`；
- concurrency：`1`；
- proxy：false；
- subcomments：false；
- detail：最多 `1` item；
- comments：最多 `1` item × `5` comments；
- real smoke：最多 `3 runs / platform(or account gate) / day`，继续以现有正式 Guard 的更严格值为准。

## 5. AI Provider / Route / Budget

Provider secret 只能通过 opaque credential reference，例如：

```text
env://OPENAI_API_KEY
```

不要在命令、Markdown、数据库普通 config、日志或 PR body 中写真实 credential。

真实 Provider E2E 最低要求：

- Provider enabled；
- credential reference 当前环境可解析；
- Provider Connection Test 成功；
- `editorial_scoring` / `draft_generation` 正式 Route enabled/active；
- AI Budget 可用；
- 至少一次正式业务 Invocation 成功；
- structured output schema validation 通过；
- Invocation / Attempt 落库；
- usage/cost 有值则如实记录，无值则 `unknown`，不能写 0 冒充已知。

## 6. MVP Doctor

只读检查：

```bash
python -m scripts.mvp_doctor
```

输出：`PASS / WARN / BLOCK`。

它只组合现有数据库真相，不修配置、不登录、不采集、不调用 AI。

典型语义：

- migration mismatch：BLOCK；
- `REVIEW_REQUIRED/RESTRICTED` account：真实平台 Gate BLOCK；
- Production Provider `NOT_TESTED`：Engineering 环境可 WARN，但真实 E2E BLOCK；
- 没有 Performance 数据：不阻止 Draft E2E；
- 历史 failed/paused-risk Run：WARN，需要人工查看原因。

## 7. M5-D Preflight

在真实网络操作之前运行：

```bash
python -m scripts.m5d_preflight \
  --platform bilibili \
  --connector-instance <CONNECTOR_INSTANCE_UUID> \
  --source <SOURCE_UUID> \
  --account <ACCOUNT_UUID> \
  --provider-id <PROVIDER_UUID> \
  --limit 1 \
  --phase e2e
```

如果只检查平台前置条件，可使用：

```bash
python -m scripts.m5d_preflight \
  --platform bilibili \
  --connector-instance <CONNECTOR_INSTANCE_UUID> \
  --source <SOURCE_UUID> \
  --account <ACCOUNT_UUID> \
  --limit 1 \
  --phase platform
```

任一 `BLOCK`：立即停止，不继续真实 Platform/Provider 操作。

## 8. Real Platform Smoke

### 8.1 首选顺序

1. Bilibili
2. Zhihu（仅在 Bilibili 前置条件不可满足时人工切换）

Weibo 当前不作为 MVP Gate 首选；如果 upstream 仍没有明确可验证的低量 search 参数，保持 `BLOCKED / KNOWN LIMITATION`，不猜参数、不逆向签名。

### 8.2 真实运行

Preflight 无 BLOCK 后，由操作者明确确认：

```bash
python -m scripts.run_m5d_platform_smoke \
  --platform bilibili \
  --connector-instance <CONNECTOR_INSTANCE_UUID> \
  --source <SOURCE_UUID> \
  --account <ACCOUNT_UUID> \
  --actor <HUMAN_ACTOR> \
  --limit 1 \
  --confirm-real-network
```

该 wrapper 仍调用现有 `scripts.mediacrawler_smoke` 与 CollectorRuntime 主链，不建立第二套采集器。

### 8.3 Risk Stop

出现任意以下信号时，当前真实验证必须立即停止：

- HTTP 403 / 406 / 429；
- CAPTCHA；
- automation detection；
- account blocked / abnormal account；
- login invalidation；
- `REVIEW_REQUIRED`；
- `RESTRICTED`；
- 现有 Risk Guard 返回其他 stop/pause 条件。

禁止 retry 到成功、换账号、换代理、重开 Profile 后继续同一验证。

结果记录为 `RISK_BLOCKED` 或 `PRECONDITION_BLOCKED`，而不是隐藏失败。

### 8.4 Platform PASS 最低证据

- CollectionRun succeeded；
- RawSignal count >= 1；
- RawSignal 有 platform/source/真实 identity/URL/collected_at；
- Checkpoint before/after 符合模式语义；
- 无风险事件；
- 无 secret 泄漏；
- 无 fake/synthetic fixture。

## 9. Production Provider Validation

真实付费调用只在受控本地执行，普通 GitHub Actions 禁止运行。

第一步：Connection Test + 显式付费确认：

```bash
python -m scripts.run_m5d_provider_validation \
  --provider-id <PROVIDER_UUID> \
  --model-id <MODEL_UUID> \
  --actor <HUMAN_ACTOR> \
  --confirm-paid-call
```

仅 Connection Test 成功时，命令会保持：

```text
PENDING_BUSINESS_INVOCATION
```

它不是 Production Provider PASS。

完成真实 `editorial_scoring` 或 `draft_generation` 业务调用并取得 Invocation ID 后，再核验：

```bash
python -m scripts.run_m5d_provider_validation \
  --provider-id <PROVIDER_UUID> \
  --model-id <MODEL_UUID> \
  --actor <HUMAN_ACTOR> \
  --business-invocation-id <REAL_BUSINESS_INVOCATION_UUID> \
  --confirm-paid-call
```

只有 Connection Test 与正式业务 Invocation/Attempt 都可核验，才可记录 Production Provider PASS。

## 10. Full Human-in-loop MVP E2E

推荐顺序：

1. Real Collection；
2. 确认 RawSignal；
3. Event 处理/绑定；
4. Evidence extraction / Human review；
5. Trend calculate；
6. 真实 Provider `editorial_scoring`；
7. Daily Candidate Preview / Apply；
8. Human 打开 Workbench 检查同一 Event；
9. Human 追加 `adopt` Decision；
10. 显式 Create Event Card；
11. 显式 Create Editorial Pack；
12. Human 显式触发真实 Provider AI Draft；
13. 运行只读 Verifier；
14. 将脱敏证据写入 Validation Report。

脚本绝不能自动 `adopt()`。Human Decision 必须有真实 human actor + reason；R3/R4 按现有 M5-B risk acknowledgement 规则执行。

## 11. Human Web 检查步骤

在同一个 Event Workbench 中人工确认：

- Sources / Timeline 含本次真实 RawSignal；
- Evidence Claim 至少一条通过 `EvidenceClaimSource` 指向真实 RawSignal；
- Unknown 状态如实；
- Trend 的 unavailable 字段仍为 NULL + reason；
- Editorial Score 来自真实 AIGateway Invocation；
- Risk 与 Recommended Format 正常；
- Candidate 使用 `candidate-ranking-v1`，有 rank/provenance；
- 人工 Decide 为 `adopt`，填写 reason；
- Card/Pack 显式创建；
- AI Draft 显式触发并通过 Risk/Citation/Stale protection。

不得为了通过 E2E 将 Claim 自动 confirmed、关闭 Risk Guard 或伪造 Candidate。

## 12. E2E Provenance Verifier

收集以下内部 ID：

- CollectionRun ID；
- Event ID；
- Candidate Run ID；
- Human Decision ID；
- Draft ID。

执行：

```bash
python -m scripts.verify_m5d_e2e \
  --collection-run-id <COLLECTION_RUN_UUID> \
  --event-id <EVENT_UUID> \
  --candidate-run-id <CANDIDATE_RUN_UUID> \
  --decision-id <DECISION_UUID> \
  --draft-id <DRAFT_UUID>
```

Verifier 只读，不会补建缺失 Artifact。它会核验 Run→RawSignal→Event→Evidence→Trend→AI Score→Candidate→Human Adopt→Card/Pack→AI Draft 与真实 Provider Invocation provenance。

如需要保存临时脱敏 JSON：

```bash
python -m scripts.verify_m5d_e2e ... --report <LOCAL_SAFE_REPORT_PATH>
```

正式提交仓库的结果应人工整理到 `docs/M5D_REAL_VALIDATION_REPORT.md`，不得提交外部正文或 secret。

## 13. 每日编辑工作流

```text
Sources / Runs health
→ Event Explorer
→ Evidence
→ Trend / Score
→ Daily Candidate Pool
→ Human Adopt / Watch / Drop / Archive
→ Card / Pack
→ Draft / Human Revision
→ Markdown Export
→ 人工在平台发布
→ Record Publication
→ Manual / CSV Performance
```

自动平台发布：**OUT OF SCOPE**。

## 14. Publication / Performance 录入

M5-C 仅记录真实已发布结果：

- `Adopt != Published`；
- `Draft != Published`；
- Publication workflow 绑定 exact Draft version；
- manual_backfill 不伪造 Candidate/Decision/Draft；
- Performance Snapshot append-only；
- missing metric = NULL，不是 0；
- CSV Preview 无副作用；
- CSV Apply 显式确认。

M5-D 不接发布 API，也不自动因 Performance 改 Score/Rank/Decision/Evidence。

## 15. 失败处理

### Provider quota / billing / credential

```text
停止 AI 操作
→ 查看 Provider validation / Invocation / Attempt
→ 查看 AI Budget
→ 修复真实配置
→ 重新 Preflight
```

不得 Fake fallback 后写 PASS。

### Platform risk

```text
停止 Collection
→ 查看 Account / Risk Dashboard
→ 保留 Risk Event / Run 证据
→ 不 retry / 不换号 / 不换代理
```

### Event merged

使用 `EVENT_MERGED + target_event_id` 跳转 canonical target；不要在旧 Event 新建 Artifact。

### Stale Candidate

刷新 Event context / 重新生成 Candidate Pool；不覆盖历史 Candidate。

### Stale Draft context

刷新 Evidence/Score/Card/Pack，再由 Human 显式重新生成；不关闭 stale protection。

## 16. 备份与恢复建议

MVP 本身不能代替正式生产备份策略。至少应在受控环境中保留 PostgreSQL 备份，并在恢复后执行：

1. Alembic head 检查；
2. Definition sync 幂等检查；
3. `python -m scripts.mvp_doctor`；
4. Connector Account/Risk/Checkpoint 检查；
5. Provider/Route/Budget 检查；
6. API/Web read-only smoke。

不要通过删除历史 Run/Decision/Draft/Performance Snapshot 来“修复”状态。

## 17. Engineering Gate

Phase 1 必须通过：

```bash
ruff check .
mypy apps packages
pytest
```

以及现有 CI：

- M3 concurrent reprocess targeted；
- M3 offline engineering evaluation；
- M3 performance baseline；
- Alembic `upgrade head → downgrade -1 → upgrade head → downgrade base → upgrade head`；
- Connector Definition sync ×2；
- Web lint/typecheck/test/build。

Engineering Gate 绿色后最多声明：

```text
M5-D Engineering Hardening COMPLETE
Real Platform Smoke PENDING
Production AI Provider Validation PENDING / NOT_TESTED
Human-in-loop E2E PENDING
M5 Overall NOT COMPLETE
AWAITING HUMAN REAL VALIDATION
```

## 18. Closeout 规则

只有以下全部成立，才能将 M5-D / M5 Overall 更新为 COMPLETE：

- M5-A/B/C COMPLETE / MERGED；
- Engineering Hardening final exact-head CI success；
- 至少一个 Bilibili 或 Zhihu Real Platform MVP Gate PASS；
- Production Provider Connection Test + 正式业务 Invocation PASS；
- Full Human-in-loop E2E Verifier PASS；
- final sanitized validation report；
- final exact-head CI success。

一平台真实 Smoke 只满足 MVP one-platform gate，不代表七个平台生产验证完成；MVP Closeout 也不代表大规模聚类质量、商业 License、账号绝对安全或自动发布已完成。
