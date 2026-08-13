export const eventStatusLabel:Record<string,string>={emerging:'初现',growing:'上升',stable:'稳定',declining:'回落',resolved:'已结束'}
export const decisionLabel:Record<string,string>={adopt:'采用',watch:'观察',drop:'放弃',archive:'归档'}
export const booleanLabel=(value:boolean)=>value?'是':'否'
export const enabledLabel=(value:boolean)=>value?'已启用':'已停用'
export const scopeLabel:Record<string,string>={global:'全局',task:'任务',provider:'服务商'}
export const policyLabel:Record<string,string>={block:'阻止调用',allow_once:'允许一次'}
export const accountStatusLabel:Record<string,string>={healthy:'正常',review_required:'进入人工复核',cooldown:'冷却中',disabled:'已停用'}
export const scheduleTypeLabel:Record<string,string>={interval:'按间隔执行',cron:'Cron 表达式'}
export const runStatusLabel:Record<string,string>={pending:'等待执行',running:'运行中',succeeded:'成功',partial:'部分成功',failed:'失败',cancelled:'已取消',paused_risk:'风险暂停'}
export const triggerTypeLabel:Record<string,string>={manual:'手动执行',schedule:'计划执行',scheduled:'计划执行',test:'测试运行',retry:'人工重试'}
export const reviewStatusLabel:Record<string,string>={pending:'待处理',review_required:'需要人工复核',reviewed:'已复核',approved:'已通过',rejected:'已拒绝'}
export const capabilityLabel:Record<string,string>={search:'搜索采集',account:'账号采集',detail:'详情采集',comments:'评论采集',feed:'订阅采集'}
export const publicationModeLabel:Record<string,string>={workflow:'工作流发布',manual_backfill:'手动补录'}
export const performanceHorizonLabel:Record<string,string>={h1:'发布后 1 小时',h24:'发布后 24 小时',d7:'发布后 7 天',custom:'自定义观察点'}
export const validationStatusLabel:Record<string,string>={NOT_TESTED:'尚未验证',PASSED:'验证通过',FAILED:'验证失败'}
export const evidenceStateLabel:Record<string,string>={confirmed:'已确认',investigating:'核验中',single_source:'单一信源',disputed:'存在争议',false:'已证伪'}
export const unknownStatusLabel:Record<string,string>={open:'待确认',resolved:'已解决',dismissed:'已忽略'}
export const providerTypeLabel:Record<string,string>={openai_compatible:'OpenAI 兼容服务',local_openai_compatible:'本地 OpenAI 兼容服务'}
export const sourceStatusLabel:Record<string,string>={active:'已启用',disabled:'已停用',archived:'已归档'}
export const sourceModeLabel:Record<string,string>={feed:'订阅采集',search:'搜索采集',account:'账号采集',detail:'详情采集',comments:'评论采集'}
export const editorialFormatLabel:Record<string,string>={daily_compilation:'每日汇编',quick_explainer:'快速解读',fact_check:'事实核查',deep_dive:'深度分析',entertainment:'娱乐内容',consumer_safety:'消费安全'}
export const draftTypeLabel:Record<string,string>={short_30s:'短稿 · 约 30 秒',standard_90s:'标准稿 · 约 90 秒',deep_180s:'深度稿 · 约 180 秒'}
export const draftStatusLabel:Record<string,string>={draft:'草稿',generated:'已生成',edited:'已编辑',revised:'已修订',approved:'已通过',archived:'已归档'}
export const citationUsageLabel:Record<string,string>={fact:'作为事实',attributed:'标明来源',disputed:'标记争议',debunked:'用于辟谣'}
export const sourceTypeLabel:Record<string,string>={ai:'AI 生成',human:'人工创建'}
export const numberLabel=(value:number|string|null|undefined,precision=2)=>value==null||value===''?'—':Number(value).toFixed(precision)
