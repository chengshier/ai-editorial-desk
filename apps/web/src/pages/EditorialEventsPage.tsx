import { useCallback,useEffect,useMemo,useState } from 'react'
import { Empty,ErrorBanner,Panel } from '../components/common'
import { Badge,EventBadge,Metric,RiskBadge,fmt } from '../components/workbench'
import type { WorkbenchApi } from '../workbenchApi'
import type { EditorialDecision,EditorialRisk,EventQuery,EventStatus,WorkbenchEventPage } from '../workbenchTypes'

const presence=[['','Any'],['true','Yes'],['false','No']] as const
export function EditorialEventsPage({api,onOpenEvent}:{api:WorkbenchApi;onOpenEvent:(id:string)=>void}){
 const[page,setPage]=useState(1);const[q,setQ]=useState('');const[status,setStatus]=useState<EventStatus|''>('');const[category,setCategory]=useState('');const[risk,setRisk]=useState<EditorialRisk|''>('');const[decision,setDecision]=useState<EditorialDecision|''>('');const[includeMerged,setIncludeMerged]=useState(false);const[hasEvidence,setHasEvidence]=useState('');const[hasScore,setHasScore]=useState('');const[hasDraft,setHasDraft]=useState('');const[updatedFrom,setUpdatedFrom]=useState('');const[updatedTo,setUpdatedTo]=useState('');const[sortBy,setSortBy]=useState<EventQuery['sortBy']>('last_updated_at');const[sortDirection,setSortDirection]=useState<'asc'|'desc'>('desc');const[data,setData]=useState<WorkbenchEventPage|null>(null);const[loading,setLoading]=useState(true);const[error,setError]=useState<string|null>(null)
 const query=useMemo<EventQuery>(()=>({page,pageSize:20,q:q||undefined,status:status||undefined,category:category||undefined,risk:risk||undefined,decision:decision||undefined,includeMerged,hasEvidence:hasEvidence?hasEvidence==='true':undefined,hasScore:hasScore?hasScore==='true':undefined,hasDraft:hasDraft?hasDraft==='true':undefined,updatedFrom:updatedFrom||undefined,updatedTo:updatedTo||undefined,sortBy,sortDirection}),[page,q,status,category,risk,decision,includeMerged,hasEvidence,hasScore,hasDraft,updatedFrom,updatedTo,sortBy,sortDirection])
 const load=useCallback(async()=>{setLoading(true);setError(null);try{setData(await api.events(query))}catch(e){setError(e instanceof Error?e.message:'Event list failed')}finally{setLoading(false)}},[api,query])
 useEffect(()=>{void load()},[load]);const resetPage=()=>setPage(1)
 return <Panel title="Event Explorer" actions={<button onClick={()=>void load()}>Refresh</button>}>
  <div className="notice">Event lifecycle is not an editorial decision. Algorithmic Candidate Rank and Human Editorial Decision are independent.</div>
  <div className="filter-grid">
   <label>Text query<input aria-label="Text query" value={q} onChange={e=>{setQ(e.target.value);resetPage()}} placeholder="Title / summary"/></label>
   <label>Lifecycle<select aria-label="Lifecycle" value={status} onChange={e=>{setStatus(e.target.value as EventStatus|'');resetPage()}}><option value="">All</option>{['emerging','growing','stable','declining','resolved'].map(v=><option key={v}>{v}</option>)}</select></label>
   <label>Editorial Decision<select aria-label="Editorial Decision filter" value={decision} onChange={e=>{setDecision(e.target.value as EditorialDecision|'');resetPage()}}><option value="">All</option>{['adopt','watch','drop','archive'].map(v=><option key={v}>{v}</option>)}</select></label>
   <label>Category<input aria-label="Category" value={category} onChange={e=>{setCategory(e.target.value);resetPage()}}/></label>
   <label>Risk<select aria-label="Risk" value={risk} onChange={e=>{setRisk(e.target.value as EditorialRisk|'');resetPage()}}><option value="">All</option>{['R0','R1','R2','R3','R4'].map(v=><option key={v}>{v}</option>)}</select></label>
   <label>Has Evidence<select aria-label="Has Evidence" value={hasEvidence} onChange={e=>{setHasEvidence(e.target.value);resetPage()}}>{presence.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label>
   <label>Has Score<select aria-label="Has Score" value={hasScore} onChange={e=>{setHasScore(e.target.value);resetPage()}}>{presence.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label>
   <label>Has Draft<select aria-label="Has Draft" value={hasDraft} onChange={e=>{setHasDraft(e.target.value);resetPage()}}>{presence.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label>
   <label>Updated from<input aria-label="Updated from" type="datetime-local" value={updatedFrom} onChange={e=>{setUpdatedFrom(e.target.value);resetPage()}}/></label>
   <label>Updated to<input aria-label="Updated to" type="datetime-local" value={updatedTo} onChange={e=>{setUpdatedTo(e.target.value);resetPage()}}/></label>
   <label>Sort<select aria-label="Sort" value={sortBy} onChange={e=>{setSortBy(e.target.value as EventQuery['sortBy']);resetPage()}}><option value="last_updated_at">Last updated</option><option value="first_seen_at">First seen</option><option value="traffic_total">Effective score</option></select></label>
   <label>Direction<select aria-label="Direction" value={sortDirection} onChange={e=>{setSortDirection(e.target.value as 'asc'|'desc');resetPage()}}><option value="desc">Descending</option><option value="asc">Ascending</option></select></label>
   <label className="check-field"><input type="checkbox" checked={includeMerged} onChange={e=>{setIncludeMerged(e.target.checked);resetPage()}}/> Include merged</label>
  </div>
  <ErrorBanner error={error}/>{loading&&<div className="section-state" role="status">Loading events…</div>}
  {!loading&&data&&data.items.length===0&&<Empty text="No Events match the current filters"/>}
  {!loading&&data&&data.items.length>0&&<div className="event-list">{data.items.map(item=>{const e=item.event,s=item.effective_editorial;return <article className="event-row" key={e.id}>
   <div className="event-main"><button className="link-button event-title" onClick={()=>onOpenEvent(e.id)}>{e.title}</button><div className="badges"><EventBadge value={e.status}/>{e.category&&<Badge>{e.category}</Badge>}{e.merged_into_event_id&&<Badge tone="danger">MERGED → {e.merged_into_event_id.slice(0,8)}</Badge>}{item.human_override_applied&&<Badge tone="warn">Human Override Applied</Badge>}{item.current_editorial_decision&&<Badge tone={item.current_editorial_decision.decision==='archive'?'danger':'info'}>Human: {item.current_editorial_decision.decision}</Badge>}{item.latest_candidate&&<Badge>Algorithmic Rank #{item.latest_candidate.rank}</Badge>}</div><small>First {fmt(e.first_seen_at)} · Updated {fmt(e.last_updated_at)}</small></div>
   <div className="event-stats"><Metric label="Sources / Platforms" value={`${e.source_count} / ${e.platform_count}`}/><Metric label="Trend" value={item.latest_trend?`${item.latest_trend.new_signal_count} new · ${item.latest_trend.signal_velocity??'Unavailable'}`:'Not calculated'}/><Metric label="Effective Score" value={s?s.traffic_total.toFixed(1):'Not scored'}/><Metric label="Risk" value={s?<RiskBadge value={s.risk_level}/>:'Not scored'}/><Metric label="Format" value={s?.recommended_format||'Unavailable'}/><Metric label="Evidence" value={`${item.evidence_total} claims`} help={`confirmed ${item.evidence_counts.confirmed} · single ${item.evidence_counts.single_source} · disputed ${item.evidence_counts.disputed}`}/><Metric label="Open Unknowns" value={item.open_unknown_count}/><Metric label="Artifacts" value={`Card ${item.card_count?'yes':'no'} · Draft ${item.draft_count}`}/></div>
  </article>})}</div>}
  {data&&<div className="pager"><span>Page {data.page} · {data.total} Events</span><button disabled={data.page<=1} onClick={()=>setPage(p=>p-1)}>Previous</button><button disabled={!data.has_next} onClick={()=>setPage(p=>p+1)}>Next</button></div>}
 </Panel>
}
