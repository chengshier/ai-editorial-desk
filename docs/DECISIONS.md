# Architecture Decisions

## D-001：第三方源码保持边界，不直接成为主系统业务层

- `third_party/` 中的工程只作为受控依赖；
- 主系统通过 adapter/subprocess/protocol 接入；
- 主系统状态、预算、风险、RawSignal、Event 等业务真相仍由主系统持有；
- 不为了接入第三方代码破坏已有领域边界。

## D-002：平台账号只保存引用，不保存敏感凭证

- `PlatformAccount` 保存 `credential_ref`、`browser_profile_ref` 等引用；
- Cookie、Authorization、密码、Token 不进入普通业务配置、API response 或审计快照；
- 敏感材料必须由受控运行环境解析。

## D-003：Checkpoint 使用明确复合 Scope

Checkpoint 的业务唯一性由 connector instance、platform account、mode、scope key 等明确维度决定；空账号也必须保持稳定唯一语义，避免重复 checkpoint。

## D-004：RawSignal 是不可变事实层

- 采集后不因后续聚类、Evidence、Scoring 被改写；
- 通过稳定 idempotency key 防止重复采集；
- 派生能力建立独立 artifact，不把派生结果回写为 RawSignal 事实。

## D-005：平台风险状态与普通技术失败分离

CAPTCHA、登录失效、权限限制、自动化检测、账号异常等属于平台风险；网络 timeout、DNS、临时 5xx 等属于技术失败。两者不得用同一普通 retry 语义处理。

## D-006：敏感配置禁止进入普通 Connector Config

Connector config/schema 对 cookie、authorization、access token、password、client secret、session、credential 等敏感键 fail closed；账号凭证只能通过受控引用解析。

## D-007：配置变更审计只保存脱敏前后快照

`ConfigurationChangeLog` 保存 actor、entity、action、before/after 等审计信息，但快照使用 Sanitized JSON，不保存可直接使用的凭证。

## D-008：Collection Run 使用明确状态机

Run 的开始、成功、部分成功、失败、风险暂停等状态必须显式；失败不能被错误标成成功，checkpoint 也只能在安全条件下推进。

## D-009：Manual / RSS 网络获取复用统一 SSRF 与边界保护

- 只允许 HTTP(S)；
- 拒绝 localhost、私网、链路本地等非公网目标；
- redirect 重新校验；
- response size/timeouts 有上限；
- 内容解析失败与网络失败显式区分。

## D-010：Budget 与 Run Claim 必须具备数据库并发语义

预算 reservation/settlement 和 schedule/run claim 不能只依赖进程内锁；真实 PostgreSQL 约束/锁保证并发不超额、不重复执行。

## D-011：Scheduler 状态持久化，不把 Cron 当业务真相

Schedule、lease、trigger、heartbeat 与 recovery 都保存到数据库；进程重启后可以恢复，不依赖单机内存 Cron 状态。

## D-012：低量真实验证只能通过明确 Smoke Gate 开启

默认能力与真实低量验证能力分离；只有经过审计、预算、风险与人工确认的 mode/platform 才允许低量 smoke，且不包含验证码破解、指纹伪造、自动换号或代理轮换。

## D-013：MediaCrawler 通过受控协议接入

MediaCrawler 保持 `third_party` 边界，通过版本化 subprocess envelope 与主系统交换有限 JSON 数据；主系统仍负责 CollectorRuntime、Run、Checkpoint、Budget、Risk Guard 与 RawSignal。

## D-014：七平台 Mapper 与能力矩阵显式注册

每个平台使用独立 Mapper 适配第三方真实 shape；能力表与代码 Registry 一一对应，不能对第三方尚未支持的能力做“形式上可用”的声明。

## D-015：Incremental / Account Profile / SignatureProvider / Risk 均采用保守语义

- checkpoint protocol 版本化；
- 只有排序可证明安全时才按时间 watermark early stop；
- browser profile 只能解析受控已有路径；
- SignatureProvider 是代码拥有的显式扩展点；
- 平台风险不降级为普通技术 retry。

## D-016：M2 Engineering Complete 与真实平台验证状态分离

M2 工程能力可以 COMPLETE，但 Real Smoke / Real-world Validation 必须独立记录。没有真实受控平台验证时继续 `DEFERRED / NOT_TESTED`，不能由 CI/synthetic test 推导为 PASSED。

## D-017：Event / EventSignal 是独立事件层与显式来源关系

- Event 是后续派生分析主体；
- EventSignal 保存 Event 与 RawSignal 的真实 membership/provenance；
- manual/algorithm attach 来源显式；
- merge 保留 source Event 与 `merged_into_event_id`，不删除历史。

## D-018：Embedding 是版本化派生 artifact

Signal embedding 与 RawSignal 分离；provider/model/dimensions/version/input schema/input hash 都形成 provenance。不同 embedding version/dimensions 不直接比较；RawSignal 不被 embedding 修改。

## D-019：Matching / Clustering 先确定性规则，再可解释组合

Exact duplicate、SimHash、Embedding recall、时间边界与人工 override 分层；所有自动 membership 必须可追溯到 algorithm version，人工 distinct/merge/split 优先于自动重处理。

## D-020：M3 收口必须包含 convergence、human boundary、offline evaluation 与 performance baseline

M3 COMPLETE 不仅是功能存在，还要求：

- 重处理收敛；
- 人工 merge/split/detach 不被自动算法静默推翻；
- versioned offline dataset/evaluation；
- PostgreSQL concurrency；
- engineering performance baseline。

## D-021：M4 统一复用一个 AI Gateway

Embedding bridge、Evidence extraction、Editorial scoring 等 AI 能力共享 Provider/Model/Route/Budget/Invocation 基础，不复制第二套 Provider HTTP 客户端作为业务路径。

## D-022：AIGateway Route / Budget / Invocation 是 AI 调用治理真相

- task key 解析 versioned route；
- Budget 在 Provider 调用前 reservation、调用后 settlement；
- retry/fallback bounded；
- Invocation/Attempt 保存 prompt/schema version、usage、cost、latency、request id 与安全 subject provenance；
- 业务 artifact 不重复保存 Provider token/cost 真相。

## D-023：Production Provider Validation 是独立状态

MockTransport/Fake Provider 的 CI 成功只证明工程契约；没有真实 production credential + network smoke 时，`Production AI Provider Validation = NOT_TESTED`。

## D-024：M3 Signal Embedding 可通过 Gateway Bridge 复用 M4-A，而不改 M3 Artifact 语义

M3 的 SignalEmbeddingRecord/version/input hash/recall 语义保持不变；M4-A 可提供统一 Gateway bridge，但不能把历史 embedding artifact 改写成新的 Provider 语义。

## D-025：M4-B Evidence / Claim 证据链基础

- Claim 必须绑定真实 Event，并通过 `EvidenceClaimSource` FK 到 RawSignal；不使用不可校验的裸 UUID 数组作为 provenance；
- AI extraction 只能创建候选 Claim/Unknown，初始状态只能是 `single_source / investigating / disputed`，不能自动写 `confirmed / false`；
- `confirmed / false` 是 Human terminal verification，需要 Actor + reason + 支撑/反驳 Evidence 条件；
- Human verification/editor note 的优先级高于 AI rerun，AI 不得静默覆盖；
- EventUnknown 是一等 artifact，resolved/dismissed 历史保留；
- merged source Event 禁止新增 Evidence；
- extraction 只经 `AIGateway.generate_structured(task_key="evidence_extraction")`，Provider 调用位于数据库长事务之外；
- prompt/schema/extraction version 显式；source content 作为 untrusted data；
- unsupported/非法 source Claim 不落正式 Claim，合法部分可形成 PARTIAL；
- Evidence/RawSignal/Invocation 的历史 FK 使用 RESTRICT 保证可审计；
- CI Mock/Fake 不改变 Production Provider Validation 的 `NOT_TESTED` 状态。

## D-026：M4-C Trend 与 Editorial Score 分层、版本化并保持 Human Priority

日期：2026-08-09

决定：

1. **Trend 与 Editorial Score 是两个不同层次。** Trend 回答“事件是否正在发酵”，Editorial Score 回答“是否值得对目标账号讲”。M4-C 不产生一个把规则特征、AI语义与风险揉在一起的最终黑箱排名。
2. **Trend Snapshot 是 append-only derived artifact。** 使用独立 `event_trend_snapshots`，版本为 `trend-calculation-v1`；时间窗、公式、normalization、availability 与 input hash 都属于历史解释的一部分，未来公式变化必须升级 version。
3. **Signal Velocity 与 Interaction Velocity 分开。** v1 可计算 `new_signal_count / window_hours`；RawSignal.metrics 当前没有跨平台统一互动语义，因此 `interaction_velocity=NULL`，并记录 `INTERACTION_NORMALIZATION_UNAVAILABLE`。禁止把不同平台点赞、播放、upvote 直接相加。
4. **Unavailable 不等于 0。** Trend 通过 `feature_availability` 和 `component_metrics.unavailable_reasons` 显式记录不可用原因；Scoring input 原样告诉模型 feature unavailable，不把 NULL 填成 0。
5. **cn_gap 不做平台硬编码。** 当前 Source 没有可靠 country/region/market classification，因此 `cn_gap=NULL` + `GEOGRAPHY_CLASSIFICATION_UNAVAILABLE`；禁止用 Reddit=海外、微博=国内等规则伪造 geography。
6. **semantic_novelty v1 明确 deferred。** M3 没有 Event centroid；M4-C 不向 Event 临时增加 centroid，也不跨 embedding version/dimensions 比较。当前没有足够简单且已验证的 bounded Event-history proxy，因此 `semantic_novelty=NULL` + `EVENT_SEMANTIC_NOVELTY_UNAVAILABLE`。未来单独升级算法版本。
7. **update_value 只使用真实可观察组件。** v1 使用 new signal、new claim、new confirmed/investigating claim、official response、correction；component metrics 保存原始计数与公式。没有可靠 media classification 时不为“新增画面”拍脑袋加分。
8. **Editorial Score 固定七维统一 0..100 integer。** `emotion / information_gap / visual_value / user_relevance / discussion / novelty / extendability`。M4-C production template 不采用技术文档早期示例中的第八维 `evidence_quality`；Evidence 强弱通过 Evidence-aware input 与 Risk guard 表达。
9. **默认模板集中版本化。** `general / score-template-general-v1` 权重固定为 `20/15/15/15/15/10/10`，总和100；不在 Service 各处散落权重，也不使用 synthetic test 自动调权。
10. **traffic_total 由 Service 重算。** 公式 `sum(dimension * weight) / 100`，模型即使返回 total 也不作为业务真相；非法 dimension 不 clamp，直接失败且不落正式 Score。
11. **规则/Trend 与 AI semantic score 分开保存。** Trend Snapshot 保留 deterministic features；EditorialScore 保存七维、risk candidate、format candidate 与 AI provenance。M4-C 不建立 DailyCandidate/TOP pool。
12. **Prompt / Schema / Scoring Service 显式版本。** `editorial-scoring-v1 / editorial-score-schema-v1 / editorial-score-service-v1`；变化必须升级版本，旧 Score 不 silent overwrite。
13. **AI 评分不能修改 Evidence。** Scoring 可读取 confirmed/investigating/single_source/disputed/false 和 Unknown，但不能创建/确认/删除 Claim，也不能修改 verification、Event membership、cluster 或 Event.status。
14. **Risk candidate 与 Evidence consistency guard 分层。** AI 可建议 R0-R4，但无 Evidence、无 confirmed Claim、全部 single_source/disputed、存在 open Unknown 时不能给 R0。没有 Source Credibility 时不建立平台=可信等级硬编码。
15. **R4 是表达风险，不是删除指令。** R4 Event 保留；“谣言已证伪”等内容仍可作为 `fact_check` 候选。
16. **recommended_format 是有限候选 key，不是 Draft。** v1 key：`daily_compilation / quick_explainer / fact_check / deep_dive / entertainment / consumer_safety`。M4-D 才真正生成标题、Event Card、Script/Draft。
17. **Human Score 不依赖 AI。** 人工可创建完整七维 Score，要求 Actor + reason，`source_type=human`，不伪造 AI Invocation，并写 AuditLog。
18. **Human Override append-only。** Override 可修改七维/risk/format，要求 Actor + reason；原始 Score 保留。Effective view 应用人工决定，后续 AI rerun 可以产生新 Score，但不能静默抹掉 Human override。
19. **AI Score 历史 append-only + 输入幂等。** 相同 event/trend/template/scoring/input hash 的 apply 返回既有有效 artifact，不无限创建重复 Score；输入或版本变化可以形成新的历史 Score。
20. **Provider 调用只经 AIGateway 且脱离数据库长事务。** Snapshot 短事务 → AIGateway Route/Budget/Retry/Fallback/Schema/Invocation/Attempt/Usage/Cost → 新短事务重新检查 active Event → 保存 Score。Preview 仍可能有成本，但不写正式 Score。
21. **merged Event 与历史审计保持一致。** source Event 已 merged 时禁止新增 Trend/Score/Override，返回 `EVENT_MERGED + target_event_id`；历史 artifact 仍可读取。
22. **Production Provider Validation 保持独立。** M4-C CI 全部使用 Mock/Fake；这不能把 `Production AI Provider Validation = NOT_TESTED` 改成 PASSED/VERIFIED。
23. **M4-C 不进入 M4-D/M5。** 不实现 Event Card、标题、Hook、Candidate Pack、Script、Draft、DailyCandidate、Publication Feedback 或自动权重学习。
