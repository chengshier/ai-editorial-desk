import { Empty } from '../common'
import { Badge,fmt } from '../workbench'
import type { EditorialDraft } from '../../workbenchTypes'
import { draftStatusLabel,draftTypeLabel,editorialFormatLabel,sourceTypeLabel } from '../../uiLabels'

export function DraftChainView({drafts,selectedId,onSelect}:{drafts:EditorialDraft[];selectedId:string|null;onSelect:(id:string)=>void}){
 const chains=new Map<string,EditorialDraft[]>()
 drafts.forEach(d=>chains.set(d.draft_chain_id,[...(chains.get(d.draft_chain_id)||[]),d]))
 if(!chains.size)return <Empty text="暂无 Draft"/>
 return <div>{[...chains.entries()].map(([id,versions])=><section className="draft-chain" key={id}><h4>版本链 {id.slice(0,8)}…</h4>{versions.sort((a,b)=>a.draft_version-b.draft_version).map(d=><button key={d.id} className={`draft-version ${selectedId===d.id?'active':''}`} onClick={()=>onSelect(d.id)}><Badge tone={d.source_type==='ai'?'info':'ok'}>{sourceTypeLabel[d.source_type]||d.source_type}</Badge><strong>v{d.draft_version}</strong><span>{draftTypeLabel[d.draft_type]||d.draft_type} · {d.duration_target_seconds} 秒 · {editorialFormatLabel[d.format_key]||d.format_key}</span><span>{draftStatusLabel[d.status]||d.status} · {fmt(d.created_at)}</span>{d.parent_draft_id&&<small>父版本 {d.parent_draft_id.slice(0,8)}…</small>}{d.ai_invocation_id&&<small>AI 调用 {d.ai_invocation_id}</small>}</button>)}</section>)}</div>
}
