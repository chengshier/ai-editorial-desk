import { useEffect, useState } from 'react'
import { AdminApi } from '../api'
import { ErrorBanner, Panel } from '../components/common'
import type { Instance, Source } from '../types'

export function SourcesPage({ api }: { api: AdminApi }) {
  const [sources, setSources] = useState<Source[]>([]); const [instances, setInstances] = useState<Instance[]>([])
  const [form, setForm] = useState({ connector_instance_id: '', name: '', source_type: 'rss', mode: 'feed', scope_key: '', external_ref: '' })
  const [error, setError] = useState<string | null>(null)
  const load = async () => { try { const [a,b] = await Promise.all([api.page<Source>('/api/v1/admin/sources?page_size=100'), api.page<Instance>('/api/v1/admin/connector-instances?page_size=100')]); setSources(a.items); setInstances(b.items); if (!form.connector_instance_id && b.items[0]) setForm((v) => ({...v, connector_instance_id:b.items[0].id})) } catch(e){setError((e as Error).message)} }
  useEffect(() => { void load() }, [])
  const create = async () => { try { await api.post('/api/v1/admin/sources', {...form, external_ref: form.external_ref || null, config: {}, enabled:true}); setForm((v)=>({...v,name:'',scope_key:'',external_ref:''})); await load() } catch(e){setError((e as Error).message)} }
  const toggle = async (source: Source) => { try { await api.patch(`/api/v1/admin/sources/${source.id}`, {enabled: !source.enabled}); await load() } catch(e){setError((e as Error).message)} }
  return <><Panel title="Sources"><ErrorBanner error={error}/><div className="form-grid">
    <label>实例<select value={form.connector_instance_id} onChange={(e)=>setForm({...form,connector_instance_id:e.target.value})}>{instances.map((i)=><option key={i.id} value={i.id}>{i.name}</option>)}</select></label>
    <label>名称<input value={form.name} onChange={(e)=>setForm({...form,name:e.target.value})}/></label><label>类型<input value={form.source_type} onChange={(e)=>setForm({...form,source_type:e.target.value})}/></label><label>模式<input value={form.mode} onChange={(e)=>setForm({...form,mode:e.target.value})}/></label><label>Scope Key<input value={form.scope_key} onChange={(e)=>setForm({...form,scope_key:e.target.value})}/></label><label>External Ref<input value={form.external_ref} onChange={(e)=>setForm({...form,external_ref:e.target.value})}/></label></div><button onClick={create}>新建 Source</button></Panel>
    <Panel title="Source 列表" actions={<button onClick={load}>刷新</button>}><div className="table-wrap"><table><thead><tr><th>名称</th><th>类型/模式</th><th>Scope</th><th>状态</th><th>操作</th></tr></thead><tbody>{sources.map((s)=><tr key={s.id}><td>{s.name}</td><td>{s.source_type}/{s.mode}</td><td>{s.scope_key}</td><td>{s.status} / {s.enabled?'启用':'停用'}</td><td className="actions"><button onClick={()=>toggle(s)}>{s.enabled?'停用':'启用'}</button><button className="danger" onClick={async()=>{if(confirm('归档 Source？历史 Raw Signal 不会删除。')){await api.post(`/api/v1/admin/sources/${s.id}/archive`); await load()}}}>归档</button></td></tr>)}</tbody></table></div></Panel></>
}
