import { useCallback, useEffect, useState } from 'react'
import { AdminApi } from '../api'
import { Empty, ErrorBanner, Panel } from '../components/common'
import { scheduleTypeLabel } from '../uiLabels'
import type { Schedule, Source } from '../types'

export function SchedulesPage({ api }: { api: AdminApi }) {
  const [items, setItems] = useState<Schedule[]>([])
  const [sources, setSources] = useState<Source[]>([])
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({
    source_id: '',
    name: '',
    schedule_type: 'interval' as 'interval' | 'cron',
    interval_seconds: 900,
    cron_expression: '',
    timezone: 'Asia/Shanghai',
    requested_limit: 20,
  })

  const load = useCallback(async () => {
    try {
      const [schedulePage, sourcePage] = await Promise.all([
        api.page<Schedule>('/api/v1/admin/schedules?page_size=100'),
        api.page<Source>('/api/v1/admin/sources?page_size=100'),
      ])
      setItems(schedulePage.items)
      setSources(sourcePage.items)
      if (sourcePage.items[0]) {
        setForm((current) => current.source_id ? current : { ...current, source_id: sourcePage.items[0].id })
      }
    } catch (e) {
      setError((e as Error).message)
    }
  }, [api])

  useEffect(() => {
    void load()
  }, [load])

  const create = async () => {
    const source = sources.find((item) => item.id === form.source_id)
    if (!source) return setError('请选择信源')
    try {
      await api.post('/api/v1/admin/schedules', {
        connector_instance_id: source.connector_instance_id,
        source_id: source.id,
        platform_account_id: null,
        name: form.name,
        schedule_type: form.schedule_type,
        interval_seconds: form.schedule_type === 'interval' ? form.interval_seconds : null,
        cron_expression: form.schedule_type === 'cron' ? form.cron_expression : null,
        timezone: form.timezone,
        requested_limit: form.requested_limit,
      })
      await load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return <>
    <Panel title="创建采集任务"><div className="page-intro"><p>为指定信源创建周期性或单次采集任务。</p></div><ErrorBanner error={error}/><div className="form-grid"><label>信源<select value={form.source_id} onChange={(event) => setForm({ ...form, source_id: event.target.value })}>{sources.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}</select></label><label>任务名称<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })}/></label><label>调度方式<select value={form.schedule_type} onChange={(event) => setForm({ ...form, schedule_type: event.target.value as 'interval' | 'cron' })}><option value="interval">按间隔执行</option><option value="cron">Cron 表达式</option></select></label>{form.schedule_type === 'interval' ? <label>执行间隔<input type="number" min="300" value={form.interval_seconds} onChange={(event) => setForm({ ...form, interval_seconds: Number(event.target.value) })}/><small>当前：{form.interval_seconds} 秒（约 {Math.round(form.interval_seconds/60)} 分钟）</small></label> : <label>Cron 表达式<input value={form.cron_expression} placeholder="0 */6 * * *" onChange={(event) => setForm({ ...form, cron_expression: event.target.value })}/></label>}<label>时区<input value={form.timezone} onChange={(event) => setForm({ ...form, timezone: event.target.value })}/></label><label>单次采集上限<input type="number" min="1" max="100" value={form.requested_limit} onChange={(event) => setForm({ ...form, requested_limit: Number(event.target.value) })}/></label></div><button className="primary" onClick={create}>创建采集任务</button></Panel>
    <Panel title="已有采集任务" actions={<button onClick={load}>刷新</button>}>{items.length===0?<Empty text="暂无采集任务"/>:<div className="table-wrap"><table><thead><tr><th>名称</th><th>调度方式</th><th>下次运行</th><th>最近运行</th><th>状态</th><th>操作</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td>{item.name}</td><td>{scheduleTypeLabel[item.schedule_type]}{item.interval_seconds ? ` · ${item.interval_seconds} 秒` : ''}</td><td>{new Date(item.next_run_at).toLocaleString()}</td><td>{item.last_run_id || '暂无'}</td><td>{item.enabled ? '已启用' : '已暂停'}{item.paused_reason ? ` · ${item.paused_reason}` : ''}</td><td className="actions"><button onClick={async () => { await api.post(`/api/v1/admin/schedules/${item.id}/${item.enabled ? 'pause' : 'resume'}`, item.enabled ? { reason: 'Web 管理员暂停' } : {}); await load() }}>{item.enabled ? '暂停' : '恢复'}</button><button onClick={async () => { await api.post(`/api/v1/admin/schedules/${item.id}/run-now`, {}); await load() }}>立即运行</button></td></tr>)}</tbody></table></div>}<p className="muted-text">创建任务后，可在这里查看下次运行时间、最近运行与当前状态。</p></Panel>
  </>
}
