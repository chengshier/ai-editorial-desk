import { useMemo,useState } from 'react'
import { AdminApi,clearSessionConfig,loadSessionConfig,saveSessionConfig,type SessionConfig } from './api'
import { WorkbenchApi } from './workbenchApi'
import { AIBudgetsPage } from './pages/AIBudgetsPage'
import { AIInvocationsPage } from './pages/AIInvocationsPage'
import { AIProvidersPage } from './pages/AIProvidersPage'
import { AIRoutesPage } from './pages/AIRoutesPage'
import { AccountsRiskPage } from './pages/AccountsRiskPage'
import { CheckpointsPage } from './pages/CheckpointsPage'
import { DefinitionsPage } from './pages/DefinitionsPage'
import { InstancesPage } from './pages/InstancesPage'
import { RunsPage } from './pages/RunsPage'
import { SchedulesPage } from './pages/SchedulesPage'
import { SourcesPage } from './pages/SourcesPage'
import { EditorialOverviewPage } from './pages/EditorialOverviewPage'
import { EditorialEventsPage } from './pages/EditorialEventsPage'
import { EventWorkbenchPage } from './pages/EventWorkbenchPage'

type PageKey='overview'|'events'|'sources'|'schedules'|'runs'|'checkpoints'|'risk'|'definitions'|'instances'|'ai-providers'|'ai-routes'|'ai-budgets'|'ai-invocations'
type NavItem=readonly[PageKey,string]
type NavGroup={label:string;items:readonly NavItem[]}
const groups:readonly NavGroup[]=[
 {label:'Editorial',items:[['overview','Overview'],['events','Events']]},
 {label:'Collection',items:[['sources','Sources'],['schedules','Schedules'],['runs','Runs'],['checkpoints','Checkpoints'],['risk','Accounts / Risk']]},
 {label:'Configuration',items:[['definitions','Definitions'],['instances','Instances']]},
 {label:'AI',items:[['ai-providers','AI Providers'],['ai-routes','AI Routes'],['ai-budgets','AI Budgets'],['ai-invocations','AI Invocations']]},
]
const allPages:NavItem[]=groups.flatMap(group=>[...group.items])

export default function App(){
 const[page,setPage]=useState<PageKey>('overview'),[eventId,setEventId]=useState<string|null>(null);const[config,setConfig]=useState<SessionConfig>(()=>loadSessionConfig()),[draft,setDraft]=useState(config);const adminApi=useMemo(()=>new AdminApi(config),[config]),workbench=useMemo(()=>new WorkbenchApi(adminApi),[adminApi]);const tokenConfigured=Boolean(config.adminToken),actorConfigured=Boolean(config.actorId),fullyConfigured=tokenConfigured&&actorConfigured
 const apply=()=>{saveSessionConfig(draft);setConfig(draft)},clear=()=>{clearSessionConfig();const blank={...draft,adminToken:'',actorId:''};setDraft(blank);setConfig(blank)}
 const navigate=(key:string)=>{const item=allPages.find(([candidate])=>candidate===key);if(item){setEventId(null);setPage(item[0])}};const openEvent=(id:string)=>{setEventId(id);setPage('events')}
 const title=eventId?'Event Workbench':allPages.find(([key])=>key===page)?.[1]
 return <div className="app-shell"><aside className="sidebar"><div><h1>AI 编辑部</h1><p>M5-A Editorial Workbench</p></div><nav>{groups.map(group=><section className="nav-group" key={group.label}><span>{group.label}</span>{group.items.map(([key,label])=><button key={key} className={!eventId&&page===key?'active':''} onClick={()=>navigate(key)}>{label}</button>)}</section>)}</nav><div className="auth-box"><label>API Base<input value={draft.apiBaseUrl} onChange={e=>setDraft({...draft,apiBaseUrl:e.target.value})}/></label><label>Admin Token<input type="password" autoComplete="off" value={draft.adminToken} onChange={e=>setDraft({...draft,adminToken:e.target.value})}/></label><label>Actor ID<input value={draft.actorId} onChange={e=>setDraft({...draft,actorId:e.target.value})}/></label><div className="actions"><button onClick={apply}>应用会话配置</button><button onClick={clear}>清除</button></div><small>Token / Actor 仅存 sessionStorage。Workbench 不建设新的 RBAC，也不把敏感配置写入页面数据。</small></div></aside><main><header className="topbar"><div><strong>{title}</strong><span className={`connection ${fullyConfigured?'ok':'warn'}`}>{fullyConfigured?'Admin + Actor 已配置':tokenConfigured?'Read ready · Configure Actor ID':'请配置 Admin Token / Actor'}</span></div><span>内部编辑工作台 · AI 操作必须显式触发</span></header><div className="content">
  {eventId?<EventWorkbenchPage api={workbench} eventId={eventId} actorConfigured={actorConfigured} onBack={()=>setEventId(null)} onOpenEvent={openEvent}/>:<>
   {page==='overview'&&<EditorialOverviewPage api={workbench} onNavigate={navigate}/>} {page==='events'&&<EditorialEventsPage api={workbench} onOpenEvent={openEvent}/>} {page==='definitions'&&<DefinitionsPage api={adminApi}/>} {page==='instances'&&<InstancesPage api={adminApi}/>} {page==='sources'&&<SourcesPage api={adminApi}/>} {page==='schedules'&&<SchedulesPage api={adminApi}/>} {page==='runs'&&<RunsPage api={adminApi}/>} {page==='checkpoints'&&<CheckpointsPage api={adminApi}/>} {page==='risk'&&<AccountsRiskPage api={adminApi}/>} {page==='ai-providers'&&<AIProvidersPage api={adminApi}/>} {page==='ai-routes'&&<AIRoutesPage api={adminApi}/>} {page==='ai-budgets'&&<AIBudgetsPage api={adminApi}/>} {page==='ai-invocations'&&<AIInvocationsPage api={adminApi}/>} 
  </>}
 </div></main></div>
}
