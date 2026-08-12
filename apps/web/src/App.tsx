import { useMemo,useState } from 'react'
import { Activity, Blocks, BookmarkCheck, CalendarClock, CircleDot, Cpu, History, LayoutDashboard, ListChecks, Menu, PlugZap, Route, Rss, ScrollText, Send, ShieldAlert, Sparkles, UserRound, WalletCards, type LucideIcon } from 'lucide-react'
import { AdminApi,clearSessionConfig,loadSessionConfig,saveSessionConfig,type SessionConfig } from './api'
import { EventPublicationSection } from './components/editorial/EventPublicationSection'
import { EditorialWorkflowApi } from './editorialWorkflowApi'
import { PublicationApi } from './publicationApi'
import { WorkbenchApi } from './workbenchApi'
import { AIBudgetsPage } from './pages/AIBudgetsPage'
import { AIInvocationsPage } from './pages/AIInvocationsPage'
import { AIProvidersPage } from './pages/AIProvidersPage'
import { AIRoutesPage } from './pages/AIRoutesPage'
import { AccountsRiskPage } from './pages/AccountsRiskPage'
import { CheckpointsPage } from './pages/CheckpointsPage'
import { DefinitionsPage } from './pages/DefinitionsPage'
import { EditorialCandidatesPage } from './pages/EditorialCandidatesPage'
import { EditorialEventsPage } from './pages/EditorialEventsPage'
import { EditorialOverviewPage } from './pages/EditorialOverviewPage'
import { EventWorkbenchPage } from './pages/EventWorkbenchPage'
import { InstancesPage } from './pages/InstancesPage'
import { PerformancePage } from './pages/PerformancePage'
import { PublicationsPage } from './pages/PublicationsPage'
import { RunsPage } from './pages/RunsPage'
import { SchedulesPage } from './pages/SchedulesPage'
import { SourcesPage } from './pages/SourcesPage'

type PageKey='overview'|'candidates'|'events'|'publications'|'performance'|'sources'|'schedules'|'runs'|'checkpoints'|'risk'|'definitions'|'instances'|'ai-providers'|'ai-routes'|'ai-budgets'|'ai-invocations'
type NavItem=readonly[PageKey,string,LucideIcon]
type NavGroup={label:string;items:readonly NavItem[]}
const groups:readonly NavGroup[]=[
 {label:'编辑工作',items:[['overview','今日总览',LayoutDashboard],['candidates','候选池',ListChecks],['events','事件',CircleDot],['publications','发布',Send],['performance','效果反馈',Activity]]},
 {label:'内容资源',items:[['sources','信源',Rss],['schedules','采集任务',CalendarClock],['runs','运行记录',History],['checkpoints','检查点',BookmarkCheck],['risk','账号 / 风险',ShieldAlert]]},
 {label:'系统配置',items:[['definitions','连接器定义',Blocks],['instances','连接器实例',PlugZap]]},
 {label:'AI',items:[['ai-providers','AI 服务商',Cpu],['ai-routes','AI 路由',Route],['ai-budgets','AI 预算',WalletCards],['ai-invocations','AI 调用记录',ScrollText]]},
]
const allPages:NavItem[]=groups.flatMap(group=>[...group.items])
const pageDescriptions:Record<PageKey,string>={overview:'优先处理高风险、需要人工判断的编辑事项',candidates:'浏览候选快照并记录人工编辑判断',events:'核验事件上下文并推进内容生产',publications:'只记录真实已发布结果',performance:'读取已录入的发布表现反馈',sources:'管理采集来源与运行状态',schedules:'安排和查看采集调度',runs:'检查采集任务执行情况',checkpoints:'查看采集进度与恢复点',risk:'管理平台账号与风险事件',definitions:'查看系统已注册的连接器及能力',instances:'管理连接器实例','ai-providers':'管理 AI Provider 可用性','ai-routes':'管理 AI 路由与版本','ai-budgets':'查看 AI 预算约束','ai-invocations':'审计 AI 调用元数据'}

export default function App(){
 const[page,setPage]=useState<PageKey>('overview'),[eventId,setEventId]=useState<string|null>(null);const[config,setConfig]=useState<SessionConfig>(()=>loadSessionConfig()),[draft,setDraft]=useState(config);const adminApi=useMemo(()=>new AdminApi(config),[config]),workbench=useMemo(()=>new WorkbenchApi(adminApi),[adminApi]),workflow=useMemo(()=>new EditorialWorkflowApi(adminApi),[adminApi]),publication=useMemo(()=>new PublicationApi(adminApi),[adminApi]);const tokenConfigured=Boolean(config.adminToken),actorConfigured=Boolean(config.actorId),fullyConfigured=tokenConfigured&&actorConfigured
 const apply=()=>{saveSessionConfig(draft);setConfig(draft)},clear=()=>{clearSessionConfig();const blank={...draft,adminToken:'',actorId:''};setDraft(blank);setConfig(blank)}
 const navigate=(key:string)=>{const item=allPages.find(([candidate])=>candidate===key);if(item){setEventId(null);setPage(item[0])}};const openEvent=(id:string)=>{setEventId(id);setPage('events')}
 const title=eventId?'事件工作台':allPages.find(([key])=>key===page)?.[1]
 const description=eventId?'阅读、核验并推进该事件的编辑工作流':pageDescriptions[page]
 return <div className="app-shell"><aside className="sidebar"><div className="brand"><span className="brand-mark" aria-hidden="true"><Sparkles size={20}/></span><div><h1>AI 编辑部</h1><p>Editorial Intelligence</p></div></div><nav>{groups.map(group=><section className="nav-group" key={group.label}><span>{group.label}</span>{group.items.map(([key,label,Icon])=><button key={key} className={!eventId&&page===key?'active':''} onClick={()=>navigate(key)}><Icon className="nav-icon" size={18} strokeWidth={1.8}/><span>{label}</span></button>)}</section>)}</nav><details className="auth-box"><summary><span className="session-label"><UserRound size={16}/>会话与编辑身份</span><span className={`connection ${fullyConfigured?'ok':'warn'}`}>{fullyConfigured?'已就绪':'待配置'}</span></summary><div className="auth-fields"><label>API 地址<input value={draft.apiBaseUrl} onChange={e=>setDraft({...draft,apiBaseUrl:e.target.value})}/></label><label>管理员 Token<input type="password" autoComplete="off" value={draft.adminToken} onChange={e=>setDraft({...draft,adminToken:e.target.value})}/></label><label>执行者 ID<input value={draft.actorId} onChange={e=>setDraft({...draft,actorId:e.target.value})}/></label><div className="actions"><button className="primary" onClick={apply}>应用会话配置</button><button onClick={clear}>清除</button></div><small>Token 与执行者 ID 仅存于 sessionStorage；发布、效果反馈和人工判断写操作仍要求显式执行者。</small></div></details></aside><main className="main-shell"><header className="topbar"><div className="topbar-title"><Menu className="topbar-menu" size={21} aria-hidden="true"/><span><strong>{title}</strong><small>{description}</small></span></div><span className={`connection ${fullyConfigured?'ok':'warn'}`}>{fullyConfigured?'管理员与执行者已配置':tokenConfigured?'只读已就绪 · 请配置执行者 ID':'请配置管理员 Token 与执行者 ID'}</span></header><div className="content"><div className="page-inner">
  {eventId?<><EventWorkbenchPage api={workbench} workflowApi={workflow} eventId={eventId} actorConfigured={actorConfigured} onBack={()=>setEventId(null)} onOpenEvent={openEvent}/><EventPublicationSection api={publication} eventId={eventId} onNavigate={navigate}/></>:<>
   {page==='overview'&&<EditorialOverviewPage api={workbench} onNavigate={navigate}/>} {page==='candidates'&&<EditorialCandidatesPage api={workflow} publicationApi={publication} actorConfigured={actorConfigured} onOpenEvent={openEvent}/>} {page==='events'&&<EditorialEventsPage api={workbench} onOpenEvent={openEvent}/>} {page==='publications'&&<PublicationsPage api={publication} workbench={workbench} actorConfigured={actorConfigured} onOpenEvent={openEvent}/>} {page==='performance'&&<PerformancePage api={publication} actorConfigured={actorConfigured}/>} {page==='definitions'&&<DefinitionsPage api={adminApi}/>} {page==='instances'&&<InstancesPage api={adminApi}/>} {page==='sources'&&<SourcesPage api={adminApi}/>} {page==='schedules'&&<SchedulesPage api={adminApi}/>} {page==='runs'&&<RunsPage api={adminApi}/>} {page==='checkpoints'&&<CheckpointsPage api={adminApi}/>} {page==='risk'&&<AccountsRiskPage api={adminApi}/>} {page==='ai-providers'&&<AIProvidersPage api={adminApi}/>} {page==='ai-routes'&&<AIRoutesPage api={adminApi}/>} {page==='ai-budgets'&&<AIBudgetsPage api={adminApi}/>} {page==='ai-invocations'&&<AIInvocationsPage api={adminApi}/>} 
  </>}
 </div></div></main></div>
}
