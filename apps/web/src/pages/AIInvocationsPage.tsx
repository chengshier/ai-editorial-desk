import { useCallback, useEffect, useState } from 'react'
import type { AdminApi } from '../api'
import type { AiInvocation, AiInvocationDetail } from '../aiTypes'

type Props = { api: AdminApi }

export function AIInvocationsPage({ api }: Props) {
  const [items, setItems] = useState<AiInvocation[]>([])
  const [selected, setSelected] = useState<AiInvocationDetail | null>(null)
  const [task, setTask] = useState('')
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({ page: '1', page_size: '100' })
      if (task) params.set('task_key', task)
      if (status) params.set('status', status)
      const page = await api.page<AiInvocation>(`/api/v1/admin/ai/invocations?${params}`)
      setItems(page.items)
      setError('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '加载 AI Invocation 失败')
    }
  }, [api, task, status])

  useEffect(() => { void load() }, [load])

  const open = async (id: string) => {
    try {
      setSelected(await api.request<AiInvocationDetail>(`/api/v1/admin/ai/invocations/${id}`))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '加载 Invocation 详情失败')
    }
  }

  return <div className="split">
    <section className="panel">
      <div className="panel-head"><div><h2>AI Invocations</h2><small>只展示审计元数据，不展示完整 Prompt / Body / Embedding。</small></div><button onClick={() => void load()}>刷新</button></div>
      {error && <div className="error-banner">{error}</div>}
      <div className="form-grid">
        <label>Task<input value={task} onChange={e => setTask(e.target.value)} placeholder="embedding" /></label>
        <label>Status<select value={status} onChange={e => setStatus(e.target.value)}><option value="">全部</option><option value="running">running</option><option value="succeeded">succeeded</option><option value="failed">failed</option></select></label>
      </div>
      <div className="table-wrap"><table><thead><tr><th>Time</th><th>Task / Route</th><th>Provider / Model</th><th>Status</th><th>Tokens</th><th>Cost</th><th>Latency</th><th>Retry / Fallback</th><th>Error</th></tr></thead><tbody>{items.map(item => <tr key={item.id} onClick={() => void open(item.id)}><td>{new Date(item.started_at).toLocaleString()}</td><td>{item.task_key}<br /><small>v{item.route_version}</small></td><td>{item.provider_key || '-'}<br /><small>{item.model_name || '-'}</small></td><td>{item.status}</td><td>{item.total_tokens ?? '-'}</td><td>{item.estimated_cost ?? '-'}</td><td>{item.latency_ms === null ? '-' : `${item.latency_ms}ms`}</td><td>{item.retry_count} / {item.fallback_index}</td><td>{item.error_code || '-'}</td></tr>)}</tbody></table></div>
    </section>
    <aside className="panel">
      <h3>Invocation Detail</h3>
      {!selected && <div className="empty">选择一条调用记录查看 Attempt 链。</div>}
      {selected && <>
        <p><strong>{selected.id}</strong></p>
        <p>Input Hash: <code>{selected.input_hash}</code></p>
        <p>Prompt Version: {selected.prompt_version || '-'}<br />Schema Version: {selected.schema_version || '-'}</p>
        <p>Subject: {selected.subject_type || '-'} / {selected.subject_id || '-'}</p>
        <p>Provider Request ID: {selected.provider_request_id || '-'}</p>
        <h3>Attempts</h3>
        <div className="table-wrap"><table><thead><tr><th>#</th><th>Model</th><th>Status</th><th>Retry/Fallback</th><th>Error</th></tr></thead><tbody>{selected.attempts.map(attempt => <tr key={attempt.id}><td>{attempt.attempt_no}</td><td>{attempt.provider_key}<br /><small>{attempt.model_name}</small></td><td>{attempt.status}</td><td>{attempt.retry_index}/{attempt.fallback_index}</td><td>{attempt.error_code || '-'}</td></tr>)}</tbody></table></div>
        <h3>Pricing Snapshot</h3><pre className="json-view">{JSON.stringify(selected.pricing_snapshot, null, 2)}</pre>
      </>}
    </aside>
  </div>
}
