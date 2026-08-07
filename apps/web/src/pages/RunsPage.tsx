import { useCallback, useEffect, useState } from 'react'
import { AdminApi } from '../api'
import { ErrorBanner, JsonView, Panel } from '../components/common'
import type { Run } from '../types'

export function RunsPage({ api }: { api: AdminApi }) {
  const [items, setItems] = useState<Run[]>([])
  const [selected, setSelected] = useState<Run | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState('')

  const load = useCallback(async () => {
    try {
      const suffix = status ? `&status=${encodeURIComponent(status)}` : ''
      const page = await api.page<Run>(`/api/v1/admin/connector-runs?page_size=100${suffix}`)
      setItems(page.items)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [api, status])

  useEffect(() => {
    void load()
  }, [load])

  const detail = async (id: string) => {
    try {
      setSelected(await api.request<Run>(`/api/v1/admin/connector-runs/${id}`))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return <Panel title="Runs" actions={<><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">全部状态</option>{['pending', 'running', 'succeeded', 'partial', 'failed', 'cancelled', 'paused_risk'].map((item) => <option key={item}>{item}</option>)}</select><button onClick={load}>刷新</button></>}>
    <ErrorBanner error={error}/>
    <div className="split">
      <div className="table-wrap"><table><thead><tr><th>Run</th><th>触发</th><th>状态</th><th>计数</th><th>错误</th></tr></thead><tbody>{items.map((run) => <tr key={run.id} onClick={() => void detail(run.id)}><td>{run.id.slice(0, 8)}</td><td>{run.trigger_type}</td><td>{run.status}</td><td>{run.inserted_count} 插入 / {run.duplicate_count} 重复 / {run.failed_count} 失败</td><td>{run.error_code || '-'}</td></tr>)}</tbody></table></div>
      {selected && <aside><h3>Run {selected.id}</h3><p>延迟：{selected.latency_seconds ?? '-'}s · retry: {selected.retry_count}</p><p>错误：{selected.error_message || '-'}</p><div className="actions">{['failed', 'partial', 'cancelled'].includes(selected.status) && <button onClick={async () => { await api.post(`/api/v1/admin/connector-runs/${selected.id}/retry`, {}); await load() }}>人工重试</button>}{['pending', 'running'].includes(selected.status) && <button className="danger" onClick={async () => { await api.post(`/api/v1/admin/connector-runs/${selected.id}/cancel`, { reason: 'Web 管理员取消' }); await load() }}>取消</button>}</div><h4>Checkpoint Before</h4><JsonView value={selected.checkpoint_before}/><h4>Checkpoint After</h4><JsonView value={selected.checkpoint_after}/><h4>Budget</h4><JsonView value={selected.budget}/><h4>Risk Action</h4><JsonView value={selected.risk_action}/></aside>}
    </div>
  </Panel>
}
