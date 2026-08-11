import { useCallback, useEffect, useState } from 'react'
import type { AdminApi } from '../api'
import type { AiInvocation, AiInvocationDetail } from '../aiTypes'
import { numberLabel, runStatusLabel } from '../uiLabels'

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
      <div className="panel-head"><div><h2>AI 调用记录</h2><small>查看调用用途、模型、Token、成本和错误；完整 Prompt、正文与向量不会在此展示。</small></div><button onClick={() => void load()}>刷新</button></div>
      {error && <div className="error-banner">{error}</div>}
      <div className="form-grid">
        <label>用途<input value={task} onChange={e => setTask(e.target.value)} placeholder="例如 embedding" /></label>
        <label>调用状态<select value={status} onChange={e => setStatus(e.target.value)}><option value="">全部</option><option value="running">运行中</option><option value="succeeded">成功</option><option value="failed">失败</option></select></label>
      </div>
      {items.length===0?<div className="empty">暂无 AI 调用记录</div>:<div className="table-wrap"><table><thead><tr><th>时间</th><th>用途 / 路由</th><th>服务商 / 模型</th><th>状态</th><th>Token</th><th>成本</th><th>耗时</th><th>重试 / 备用</th><th>错误</th></tr></thead><tbody>{items.map(item => <tr key={item.id} onClick={() => void open(item.id)}><td>{new Date(item.started_at).toLocaleString()}</td><td>{item.task_key}<br /><small>路由 v{item.route_version}</small></td><td>{item.provider_key || '暂无'}<br /><small>{item.model_name || '暂无'}</small></td><td>{runStatusLabel[item.status]||item.status}</td><td>{item.total_tokens ?? '—'}</td><td>{numberLabel(item.estimated_cost,4)}</td><td>{item.latency_ms === null ? '—' : `${item.latency_ms} 毫秒`}</td><td>{item.retry_count} / {item.fallback_index}</td><td>{item.error_code || '无'}</td></tr>)}</tbody></table></div>}
    </section>
    <aside className="panel">
      <h3>调用详情</h3>
      {!selected && <div className="empty">选择一条调用记录查看尝试链。</div>}
      {selected && <>
        <p><strong>{selected.id}</strong></p>
        <p>用途：{selected.task_key} · 状态：{runStatusLabel[selected.status]||selected.status}</p>
        <h3>调用尝试</h3>
        <div className="table-wrap"><table><thead><tr><th>#</th><th>模型</th><th>状态</th><th>重试 / 备用</th><th>错误</th></tr></thead><tbody>{selected.attempts.map(attempt => <tr key={attempt.id}><td>{attempt.attempt_no}</td><td>{attempt.provider_key}<br /><small>{attempt.model_name}</small></td><td>{runStatusLabel[attempt.status]||attempt.status}</td><td>{attempt.retry_index}/{attempt.fallback_index}</td><td>{attempt.error_code || '无'}</td></tr>)}</tbody></table></div>
        <details><summary>查看技术元数据</summary><p>输入哈希：<code>{selected.input_hash}</code></p><p>Prompt 版本：{selected.prompt_version || '暂无'}<br />Schema 版本：{selected.schema_version || '暂无'}</p><p>关联对象：{selected.subject_type || '暂无'} / {selected.subject_id || '暂无'}</p><p>服务商请求 ID：{selected.provider_request_id || '暂无'}</p><h3>计价快照</h3><pre className="json-view">{JSON.stringify(selected.pricing_snapshot, null, 2)}</pre></details>
      </>}
    </aside>
  </div>
}
