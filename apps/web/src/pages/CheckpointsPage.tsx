import { useEffect, useState } from 'react'
import { AdminApi } from '../api'
import { ErrorBanner, JsonView, Panel } from '../components/common'
import type { Checkpoint } from '../types'

export function CheckpointsPage({ api }: { api: AdminApi }) {
  const [items,setItems]=useState<Checkpoint[]>([]);const [selected,setSelected]=useState<Checkpoint|null>(null);const [error,setError]=useState<string|null>(null)
  const load=async()=>{try{const page=await api.page<Checkpoint>('/api/v1/admin/checkpoints?page_size=100');setItems(page.items)}catch(e){setError((e as Error).message)}}
  useEffect(()=>{void load()},[])
  const reset=async(item:Checkpoint)=>{const reason=window.prompt('高风险操作：请输入重置原因');if(!reason)return;if(!window.confirm(`确认将 Checkpoint v${item.version} 重置为空？Raw Signal 不会删除。`))return;try{await api.post(`/api/v1/admin/checkpoints/${item.id}/reset`,{expected_version:item.version,reason});await load();setSelected(null)}catch(e){setError((e as Error).message)}}
  return <Panel title="Checkpoints" actions={<button onClick={load}>刷新</button>}><ErrorBanner error={error}/><div className="split"><div className="table-wrap"><table><thead><tr><th>Scope</th><th>Mode</th><th>Version</th><th>Watermark</th><th>更新时间</th><th>操作</th></tr></thead><tbody>{items.map(item=><tr key={item.id} onClick={()=>setSelected(item)}><td>{item.scope_key}</td><td>{item.mode}</td><td>v{item.version}</td><td>{item.watermark||'-'}</td><td>{new Date(item.updated_at).toLocaleString()}</td><td><button className="danger" onClick={e=>{e.stopPropagation();void reset(item)}}>高风险重置</button></td></tr>)}</tbody></table></div>{selected&&<aside><h3>{selected.scope_key}</h3><p>cursor</p><JsonView value={selected.cursor}/><p>checkpoint_data</p><JsonView value={selected.checkpoint_data}/></aside>}</div></Panel>
}
