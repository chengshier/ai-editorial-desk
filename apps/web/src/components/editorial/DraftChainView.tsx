import { Empty } from '../common'
import { Badge,fmt } from '../workbench'
import type { EditorialDraft } from '../../workbenchTypes'

export function DraftChainView({drafts,selectedId,onSelect}:{drafts:EditorialDraft[];selectedId:string|null;onSelect:(id:string)=>void}){
 const chains=new Map<string,EditorialDraft[]>()
 drafts.forEach(d=>chains.set(d.draft_chain_id,[...(chains.get(d.draft_chain_id)||[]),d]))
 if(!chains.size)return <Empty text="No Draft"/>
 return <div>{[...chains.entries()].map(([id,versions])=><section className="draft-chain" key={id}><h4>Chain {id.slice(0,8)}…</h4>{versions.sort((a,b)=>a.draft_version-b.draft_version).map(d=><button key={d.id} className={`draft-version ${selectedId===d.id?'active':''}`} onClick={()=>onSelect(d.id)}><Badge tone={d.source_type==='ai'?'info':'ok'}>{d.source_type.toUpperCase()}</Badge><strong>v{d.draft_version}</strong><span>{d.draft_type} · {d.duration_target_seconds}s · {d.format_key}</span><span>{d.status} · {fmt(d.created_at)}</span>{d.parent_draft_id&&<small>parent {d.parent_draft_id.slice(0,8)}…</small>}{d.ai_invocation_id&&<small>Invocation {d.ai_invocation_id}</small>}</button>)}</section>)}</div>
}
