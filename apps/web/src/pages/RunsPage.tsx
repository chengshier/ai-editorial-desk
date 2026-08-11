import { useCallback, useEffect, useState } from 'react'
import { AdminApi } from '../api'
import { Empty, ErrorBanner, JsonView, Panel } from '../components/common'
import { runStatusLabel, triggerTypeLabel } from '../uiLabels'
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

  return <Panel title="运行记录" actions={<><select aria-label="运行状态" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">全部状态</option>{['pending', 'running', 'succeeded', 'partial', 'failed', 'cancelled', 'paused_risk'].map((item) => <option key={item} value={item}>{runStatusLabel[item]}</option>)}</select><button onClick={load}>刷新</button></>}>
    <div className="page-intro"><p>查看采集任务的执行结果、数量统计与风险状态。</p><span className="readonly-note">历史 / 审计</span></div>
    <ErrorBanner error={error}/>
    <div className="split">
      {items.length===0?<Empty text="暂无运行记录"/>:<div className="table-wrap"><table><thead><tr><th>运行 ID</th><th>触发方式</th><th>状态</th><th>采集数量</th><th>错误 / 风险</th></tr></thead><tbody>{items.map((run) => <tr key={run.id} onClick={() => void detail(run.id)}><td>{run.id.slice(0, 8)}</td><td>{triggerTypeLabel[run.trigger_type]||run.trigger_type}</td><td>{runStatusLabel[run.status]||run.status}</td><td>{run.inserted_count} 条新增 · {run.duplicate_count} 条重复 · {run.failed_count} 条失败</td><td>{run.error_code || '无'}</td></tr>)}</tbody></table></div>}
      {selected && <aside><h3>运行详情 · {selected.id.slice(0,8)}</h3><p>耗时：{selected.latency_seconds ?? '暂无'} 秒 · 重试 {selected.retry_count} 次</p><p>错误：{selected.error_message || '无'}</p><div className="actions">{['failed', 'partial', 'cancelled'].includes(selected.status) && <button className="primary" onClick={async () => { await api.post(`/api/v1/admin/connector-runs/${selected.id}/retry`, {}); await load() }}>人工重试</button>}{['pending', 'running'].includes(selected.status) && <button className="danger" onClick={async () => { await api.post(`/api/v1/admin/connector-runs/${selected.id}/cancel`, { reason: 'Web 管理员取消' }); await load() }}>取消运行</button>}</div><details><summary>查看技术详情</summary><h4>运行前检查点</h4><JsonView value={selected.checkpoint_before}/><h4>运行后检查点</h4><JsonView value={selected.checkpoint_after}/><h4>预算信息</h4><JsonView value={selected.budget}/><h4>风险动作</h4><JsonView value={selected.risk_action}/></details></aside>}
    </div>
  </Panel>
}
