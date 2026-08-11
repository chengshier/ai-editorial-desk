import { useCallback, useEffect, useState } from 'react'
import { AdminApi } from '../api'
import { Empty, ErrorBanner, JsonView, Panel } from '../components/common'
import type { Checkpoint } from '../types'

export function CheckpointsPage({ api }: { api: AdminApi }) {
  const [items, setItems] = useState<Checkpoint[]>([])
  const [selected, setSelected] = useState<Checkpoint | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const page = await api.page<Checkpoint>('/api/v1/admin/checkpoints?page_size=100')
      setItems(page.items)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [api])

  useEffect(() => {
    void load()
  }, [load])

  const reset = async (item: Checkpoint) => {
    const reason = window.prompt('高风险操作：请输入重置原因')
    if (!reason) return
    if (!window.confirm(`确认将检查点 v${item.version} 重置为空？原始信号不会删除。`)) return
    try {
      await api.post(`/api/v1/admin/checkpoints/${item.id}/reset`, {
        expected_version: item.version,
        reason,
      })
      await load()
      setSelected(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return <Panel title="采集检查点" actions={<button onClick={load}>刷新</button>}>
    <div className="page-intro"><p>记录增量采集位置，用于下一次采集继续执行。</p><span className="readonly-note">历史 / 运维</span></div>
    <ErrorBanner error={error}/>
    <div className="split">
      {items.length===0?<Empty text="暂无采集检查点"/>:<div className="table-wrap"><table><thead><tr><th>作用范围</th><th>采集模式</th><th>版本</th><th>增量位置</th><th>更新时间</th><th>操作</th></tr></thead><tbody>{items.map((item) => <tr key={item.id} onClick={() => setSelected(item)}><td>{item.scope_key}</td><td>{item.mode}</td><td>v{item.version}</td><td>{item.watermark || '暂无'}</td><td>{new Date(item.updated_at).toLocaleString()}</td><td><button className="danger" onClick={(event) => { event.stopPropagation(); void reset(item) }}>高风险重置</button></td></tr>)}</tbody></table></div>}
      {selected && <aside><h3>{selected.scope_key}</h3><p className="muted-text">以下为增量采集的技术详情。</p><details open><summary>游标与检查点数据</summary><p>游标</p><JsonView value={selected.cursor}/><p>检查点数据</p><JsonView value={selected.checkpoint_data}/></details></aside>}
    </div>
  </Panel>
}
