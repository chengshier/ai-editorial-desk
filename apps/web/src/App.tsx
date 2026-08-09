import { useMemo, useState } from 'react'
import { AdminApi, clearSessionConfig, loadSessionConfig, saveSessionConfig, type SessionConfig } from './api'
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

const pages = [
  ['definitions','Definitions'],['instances','Instances'],['sources','Sources'],['schedules','Schedules'],['runs','Runs'],['checkpoints','Checkpoints'],['risk','Accounts / Risk'],
  ['ai-providers','AI Providers'],['ai-routes','AI Routes'],['ai-budgets','AI Budgets'],['ai-invocations','AI Invocations'],
] as const

type PageKey = typeof pages[number][0]

export default function App() {
  const [page,setPage]=useState<PageKey>('definitions')
  const [config,setConfig]=useState<SessionConfig>(()=>loadSessionConfig())
  const [draft,setDraft]=useState(config)
  const api=useMemo(()=>new AdminApi(config),[config])
  const configured=Boolean(config.adminToken&&config.actorId)
  const apply=()=>{saveSessionConfig(draft);setConfig(draft)}
  const clear=()=>{clearSessionConfig();const blank={...draft,adminToken:'',actorId:''};setDraft(blank);setConfig(blank)}
  return <div className="app-shell"><aside className="sidebar"><div><h1>AI 编辑部</h1><p>M1-M4 管理工作台</p></div><nav>{pages.map(([key,label])=><button key={key} className={page===key?'active':''} onClick={()=>setPage(key)}>{label}</button>)}</nav><div className="auth-box"><label>API Base<input value={draft.apiBaseUrl} onChange={e=>setDraft({...draft,apiBaseUrl:e.target.value})}/></label><label>Admin Token<input type="password" autoComplete="off" value={draft.adminToken} onChange={e=>setDraft({...draft,adminToken:e.target.value})}/></label><label>Actor ID<input value={draft.actorId} onChange={e=>setDraft({...draft,actorId:e.target.value})}/></label><div className="actions"><button onClick={apply}>应用会话配置</button><button onClick={clear}>清除</button></div><small>Token 仅存 sessionStorage，不写入仓库或错误日志。</small></div></aside><main><header className="topbar"><div><strong>{pages.find(([key])=>key===page)?.[1]}</strong><span className={`connection ${configured?'ok':'warn'}`}>{configured?'会话已配置':'请配置 Admin Token / Actor'}</span></div><span>内部管理工作台 · 非正式认证系统</span></header><div className="content">{page==='definitions'&&<DefinitionsPage api={api}/>} {page==='instances'&&<InstancesPage api={api}/>} {page==='sources'&&<SourcesPage api={api}/>} {page==='schedules'&&<SchedulesPage api={api}/>} {page==='runs'&&<RunsPage api={api}/>} {page==='checkpoints'&&<CheckpointsPage api={api}/>} {page==='risk'&&<AccountsRiskPage api={api}/>} {page==='ai-providers'&&<AIProvidersPage api={api}/>} {page==='ai-routes'&&<AIRoutesPage api={api}/>} {page==='ai-budgets'&&<AIBudgetsPage api={api}/>} {page==='ai-invocations'&&<AIInvocationsPage api={api}/>}</div></main></div>
}
