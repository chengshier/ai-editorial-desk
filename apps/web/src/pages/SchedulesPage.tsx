import { useCallback, useEffect, useMemo, useState } from 'react'
import { AdminApi } from '../api'
import { Drawer, Empty, ErrorBanner, ResourceHeader } from '../components/common'
import { scheduleTypeLabel } from '../uiLabels'
import type { Account, Definition, Instance, Schedule, Source } from '../types'

const initialForm = {
  source_id: '',
  platform_account_id: '',
  name: '',
  schedule_type: 'interval' as 'interval' | 'cron',
  interval_seconds: 900,
  cron_expression: '',
  timezone: 'Asia/Shanghai',
  requested_limit: 20,
}

export function SchedulesPage({ api, onNavigate }: { api: AdminApi; onNavigate?: (page: 'runs' | 'risk') => void }) {
  const [items, setItems] = useState<Schedule[]>([])
  const [sources, setSources] = useState<Source[]>([])
  const [instances, setInstances] = useState<Instance[]>([])
  const [definitions, setDefinitions] = useState<Definition[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [pageError, setPageError] = useState<string | null>(null)
  const [drawerError, setDrawerError] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [form, setForm] = useState(initialForm)

  const selectedSource = useMemo(() => sources.find((item) => item.id === form.source_id) || null, [sources, form.source_id])
  const selectedInstance = useMemo(() => selectedSource ? instances.find((item) => item.id === selectedSource.connector_instance_id) || null : null, [instances, selectedSource])
  const selectedDefinition = useMemo(() => selectedInstance ? definitions.find((item) => item.id === selectedInstance.definition_id) || null : null, [definitions, selectedInstance])
  const requiresAccount = Boolean(selectedDefinition?.capabilities.requires_account)
  const availableAccounts = useMemo(() => selectedInstance ? accounts.filter((item) => item.connector_instance_id === selectedInstance.id && item.status === 'healthy') : [], [accounts, selectedInstance])

  const load = useCallback(async () => {
    try {
      const [schedulePage, sourcePage, instancePage, definitionPage, accountPage] = await Promise.all([
        api.page<Schedule>('/api/v1/admin/schedules?page_size=100'),
        api.page<Source>('/api/v1/admin/sources?page_size=100'),
        api.page<Instance>('/api/v1/admin/connector-instances?page_size=100'),
        api.page<Definition>('/api/v1/admin/connector-definitions?page_size=100'),
        api.page<Account>('/api/v1/admin/platform-accounts?page_size=100'),
      ])
      setItems(schedulePage.items)
      setSources(sourcePage.items)
      setInstances(instancePage.items)
      setDefinitions(definitionPage.items)
      setAccounts(accountPage.items)
      setPageError(null)
    } catch (e) {
      setPageError((e as Error).message)
    }
  }, [api])

  useEffect(() => { void load() }, [load])

  const resetForm = () => {
    const source = sources[0]
    const account = source ? accounts.find((item) => item.connector_instance_id === source.connector_instance_id && item.status === 'healthy') : null
    setForm({ ...initialForm, source_id: source?.id || '', platform_account_id: account?.id || '' })
    setDrawerError(null)
  }

  const changeSource = (sourceId: string) => {
    const source = sources.find((item) => item.id === sourceId)
    const account = source ? accounts.find((item) => item.connector_instance_id === source.connector_instance_id && item.status === 'healthy') : null
    setForm((current) => ({ ...current, source_id: sourceId, platform_account_id: account?.id || '' }))
    setDrawerError(null)
  }

  const create = async () => {
    const source = sources.find((item) => item.id === form.source_id)
    if (!source) return setDrawerError('请选择信源')
    if (!form.name.trim()) return setDrawerError('请填写任务名称')
    if (form.schedule_type === 'cron' && !form.cron_expression.trim()) return setDrawerError('请填写 Cron 表达式')
    if (requiresAccount && !form.platform_account_id) return setDrawerError('该信源所属连接器需要平台账号，请先选择健康账号。')
    setPendingAction('create')
    setDrawerError(null)
    try {
      await api.post('/api/v1/admin/schedules', {
        connector_instance_id: source.connector_instance_id,
        source_id: source.id,
        platform_account_id: form.platform_account_id || null,
        name: form.name.trim(),
        schedule_type: form.schedule_type,
        interval_seconds: form.schedule_type === 'interval' ? form.interval_seconds : null,
        cron_expression: form.schedule_type === 'cron' ? form.cron_expression.trim() : null,
        timezone: form.timezone,
        requested_limit: form.requested_limit,
      })
      setMessage('采集任务已创建，并已绑定当前选择的运行账号。')
      await load()
      setDrawerOpen(false)
      resetForm()
    } catch (e) {
      setDrawerError((e as Error).message)
    } finally {
      setPendingAction(null)
    }
  }

  const changeScheduleState = async (item: Schedule) => {
    const action = item.enabled ? 'pause' : 'resume'
    setPendingAction(`${action}:${item.id}`)
    setPageError(null)
    try {
      await api.post(`/api/v1/admin/schedules/${item.id}/${action}`, item.enabled ? { reason: 'Web 管理员暂停' } : {})
      setMessage(item.enabled ? '采集任务已暂停。' : '采集任务已恢复。')
      await load()
    } catch (e) {
      setPageError((e as Error).message)
    } finally {
      setPendingAction(null)
    }
  }

  const runNow = async (item: Schedule) => {
    setPendingAction(`run:${item.id}`)
    setPageError(null)
    try {
      const result = await api.post<{ run_id?: string; status?: string }>(`/api/v1/admin/schedules/${item.id}/run-now`, {})
      setMessage(result.run_id ? `运行已创建：${result.status || '已提交'} / ${result.run_id}` : '运行请求已提交，并已刷新任务状态。')
      await load()
    } catch (e) {
      setPageError((e as Error).message)
    } finally {
      setPendingAction(null)
    }
  }

  const scheduleRequiresAccount = (item: Schedule) => {
    const instance = instances.find((candidate) => candidate.id === item.connector_instance_id)
    const definition = instance ? definitions.find((candidate) => candidate.id === instance.definition_id) : null
    return Boolean(definition?.capabilities.requires_account)
  }

  return <div className="operations-page">
    <ErrorBanner error={pageError}/>
    {message&&<div className="success-banner"><span>{message}</span>{message.startsWith('运行已创建')&&onNavigate&&<button className="quiet-action" onClick={()=>onNavigate('runs')}>查看运行记录</button>}</div>}
    <section className="panel">
      <ResourceHeader title="采集任务" description="任务决定信源何时采集。需要登录态的平台会把平台账号永久绑定到任务，后续定时执行与立即运行使用同一账号上下文。" actions={<><button onClick={() => void load()}>刷新</button><button className="primary" disabled={sources.length===0} title={sources.length===0?'请先创建并启用信源':''} onClick={() => { resetForm(); setDrawerOpen(true) }}>创建采集任务</button></>}/>
      {sources.length===0&&<div className="prerequisite-hint">当前没有可用信源。请先创建信源，再安排采集任务。</div>}
      {items.length===0 ? <Empty text="暂无采集任务" helper="创建任务后，可在这里查看下次运行时间、运行账号、最近运行与当前状态。" action={sources.length>0?<button className="primary" onClick={() => { resetForm(); setDrawerOpen(true) }}>创建采集任务</button>:undefined}/> : <div className="table-wrap"><table><thead><tr><th>名称</th><th>调度方式</th><th>运行账号</th><th>下次运行</th><th>最近运行</th><th>状态</th><th>操作</th></tr></thead><tbody>{items.map((item) => {
        const account = item.platform_account_id ? accounts.find((candidate) => candidate.id === item.platform_account_id) : null
        const needsAccount = scheduleRequiresAccount(item)
        const missingAccount = needsAccount && !item.platform_account_id
        return <tr key={item.id}>
          <td><strong>{item.name}</strong><small className="technical-meta">单次上限 {item.requested_limit}</small></td>
          <td>{scheduleTypeLabel[item.schedule_type]}{item.interval_seconds ? ` · ${item.interval_seconds} 秒` : ''}</td>
          <td><div className="status-stack"><span>{account ? account.display_name : needsAccount ? '未绑定账号' : '无需账号'}</span>{account&&<small>{account.account_identifier}</small>}{missingAccount&&<small className="warning-text">旧任务缺少账号绑定，无法运行</small>}</div></td>
          <td>{new Date(item.next_run_at).toLocaleString()}</td>
          <td>{item.last_run_id || '暂无'}</td>
          <td><div className="status-stack"><span>{item.enabled ? '已启用' : '已暂停'}</span>{item.paused_reason&&<small>{item.paused_reason}</small>}</div></td>
          <td><div className="actions action-cell"><button className="primary" disabled={Boolean(pendingAction)||!item.enabled||missingAccount} title={missingAccount?'该旧任务未绑定平台账号，请新建一个绑定账号的任务':!item.enabled?'请先恢复任务':'立即创建一次运行'} onClick={() => void runNow(item)}>{pendingAction === `run:${item.id}` ? '正在创建…' : '立即运行'}</button><button disabled={Boolean(pendingAction)} onClick={() => void changeScheduleState(item)}>{pendingAction === `${item.enabled ? 'pause' : 'resume'}:${item.id}` ? '正在处理…' : item.enabled ? '暂停' : '恢复'}</button></div>{missingAccount&&onNavigate&&<button className="inline-link" onClick={() => onNavigate('risk')}>先配置平台账号，再新建任务</button>}</td>
        </tr>
      })}</tbody></table></div>}
    </section>

    <Drawer open={drawerOpen} title="创建采集任务" description="先选择采集对象和运行账号，再设置执行方式与单次采集上限。" onClose={() => { setDrawerOpen(false); resetForm() }} footer={<><button disabled={pendingAction==='create'} onClick={() => { setDrawerOpen(false); resetForm() }}>取消</button><button className="primary" disabled={pendingAction==='create'||(requiresAccount&&!form.platform_account_id)} onClick={() => void create()}>{pendingAction==='create'?'正在保存…':'创建任务'}</button></>}>
      <ErrorBanner error={drawerError}/>
      <div className="drawer-section"><h3>采集对象</h3><p>选择一个已经配置好的信源，并给任务一个能说明用途的名称。</p><div className="form-grid"><label className="field-full">信源<select value={form.source_id} onChange={(event) => changeSource(event.target.value)}><option value="">请选择信源</option>{sources.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}</select></label><label className="field-full">任务名称<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如：B站科技热点 · 每 15 分钟"/></label></div></div>
      <div className="drawer-section"><h3>运行账号</h3><p>{requiresAccount ? '当前连接器要求平台账号。定时执行、立即运行和检查点都会使用这里绑定的账号上下文。' : '当前连接器无需平台账号，可以直接创建任务。'}</p>{requiresAccount&&<div className="form-grid"><label className="field-full">平台账号<select value={form.platform_account_id} onChange={(event) => { setForm({ ...form, platform_account_id: event.target.value }); setDrawerError(null) }}><option value="">请选择健康账号</option>{availableAccounts.map((account) => <option key={account.id} value={account.id}>{account.display_name} · {account.account_identifier}</option>)}</select></label></div>}{requiresAccount&&availableAccounts.length===0&&<div className="prerequisite-hint"><span>当前实例没有健康的平台账号，无法创建可运行任务。</span>{onNavigate&&<button className="quiet-action" onClick={() => { setDrawerOpen(false); onNavigate('risk') }}>去账号 / 风险配置</button>}</div>}</div>
      <div className="drawer-section"><h3>执行策略</h3><p>按固定间隔执行更适合常规采集；需要精确时刻时可使用 Cron。</p><div className="form-grid"><label>调度方式<select value={form.schedule_type} onChange={(event) => setForm({ ...form, schedule_type: event.target.value as 'interval' | 'cron' })}><option value="interval">按间隔执行</option><option value="cron">Cron 表达式</option></select></label>{form.schedule_type === 'interval' ? <label>执行间隔<input type="number" min="300" value={form.interval_seconds} onChange={(event) => setForm({ ...form, interval_seconds: Number(event.target.value) })}/><small>约 {Math.round(form.interval_seconds/60)} 分钟</small></label> : <label>Cron 表达式<input value={form.cron_expression} placeholder="0 */6 * * *" onChange={(event) => setForm({ ...form, cron_expression: event.target.value })}/></label>}<label>时区<input value={form.timezone} onChange={(event) => setForm({ ...form, timezone: event.target.value })}/></label><label>单次采集上限<input type="number" min="1" max="100" value={form.requested_limit} onChange={(event) => setForm({ ...form, requested_limit: Number(event.target.value) })}/></label></div></div>
    </Drawer>
  </div>
}
