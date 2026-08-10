import { useCallback,useEffect,useState } from 'react'
import { Empty,ErrorBanner,Panel } from '../components/common'
import { Metric,RiskBadge } from '../components/workbench'
import type { WorkbenchApi } from '../workbenchApi'
import type { WorkbenchOverview } from '../workbenchTypes'

export function EditorialOverviewPage({api,onNavigate}:{api:WorkbenchApi;onNavigate:(key:string)=>void}){
 const[data,setData]=useState<WorkbenchOverview|null>(null);const[error,setError]=useState<string|null>(null);const[loading,setLoading]=useState(true)
 const load=useCallback(async()=>{setLoading(true);setError(null);try{setData(await api.overview())}catch(e){setError(e instanceof Error?e.message:'Overview load failed')}finally{setLoading(false)}},[api])
 useEffect(()=>{void load()},[load])
 if(loading)return <Panel title="Editorial Overview"><div className="section-state" role="status">Loading overview…</div></Panel>
 if(error)return <Panel title="Editorial Overview"><ErrorBanner error={error}/><button onClick={()=>void load()}>Retry</button></Panel>
 if(!data)return <Panel title="Editorial Overview"><Empty text="No overview data"/></Panel>
 const life=data.lifecycle_counts,h=data.collection_health,a=data.artifact_counts
 return <>
  <div className="notice"><strong>M5-A read-only operational overview.</strong> This is not a DailyCandidate pool: no TOP ranking, adopt/watch/drop, or recommendation persistence is created here.</div>
  <Panel title="Event Pulse" actions={<button onClick={()=>void load()}>Refresh</button>}>
   <div className="metric-grid"><Metric label="Active Events" value={data.active_event_count}/><Metric label="New · 24h" value={data.recent_new_event_count_24h}/><Metric label="Updated · 24h" value={data.recent_updated_event_count_24h}/><Metric label="With Evidence" value={data.events_with_evidence_count}/><Metric label="Open Unknowns" value={data.open_unknown_count}/><Metric label="High Risk" value={data.high_risk_event_count} help="Effective R3 / R4"/></div>
   <div className="lifecycle-row">{(['emerging','growing','stable','declining','resolved'] as const).map(k=><div key={k}><span>{k}</span><strong>{life[k]}</strong></div>)}</div>
  </Panel>
  <Panel title="Editorial Artifacts"><div className="metric-grid"><Metric label="Trend Snapshots" value={a.trend_snapshots}/><Metric label="Editorial Scores" value={a.editorial_scores}/><Metric label="Event Cards" value={a.event_cards}/><Metric label="Editorial Packs" value={a.editorial_packs}/><Metric label="Drafts" value={a.drafts}/></div></Panel>
  <div className="wb-two-col">
   <Panel title="Collection / Risk Health"><div className="metric-grid compact"><Metric label="Failed Runs · 24h" value={h.failed_runs_24h}/><Metric label="Risk-paused Runs · 24h" value={h.paused_risk_runs_24h}/><Metric label="Open Risk Events" value={h.open_risk_events}/><Metric label="Paused Accounts" value={h.paused_accounts}/><Metric label="Checkpoints" value={h.checkpoint_count}/></div><div className="actions"><button onClick={()=>onNavigate('runs')}>Runs</button><button onClick={()=>onNavigate('risk')}>Accounts / Risk</button><button onClick={()=>onNavigate('checkpoints')}>Checkpoints</button><button onClick={()=>onNavigate('sources')}>Sources</button></div></Panel>
   <Panel title="Production AI Provider Validation"><div className="provider-status"><RiskBadge value="R2"/><strong>{data.production_ai_provider_validation}</strong></div><p className="muted-text">M5-A never runs a connection test or AI action on page load. Production validation remains an explicit operational gate.</p><div className="actions"><button onClick={()=>onNavigate('ai-providers')}>AI Providers</button><button onClick={()=>onNavigate('ai-routes')}>AI Routes</button><button onClick={()=>onNavigate('ai-budgets')}>AI Budgets</button></div></Panel>
  </div>
 </>
}
