import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AdminApi } from '../api'
import { AccountsRiskPage } from './AccountsRiskPage'

const page=<T,>(items:T[])=>({items,page:1,page_size:100,total:items.length,has_next:false})

it('does not render sensitive credential values returned accidentally by an API', async()=>{
  vi.stubGlobal('fetch',vi.fn(async(url:string|URL|Request)=>{
    const path=String(url)
    if(path.includes('platform-accounts')) return Response.json(page([{id:'a1',connector_instance_id:'i1',platform:'test',display_name:'账号一',account_identifier:'tester',status:'healthy',manual_review_required:false,cooldown_until:null,credential_configured:true,browser_profile_configured:true,credential_ref:'secret://must-not-render',browser_profile_ref:'profile-secret'}]))
    if(path.includes('connector-instances')) return Response.json(page([]))
    if(path.includes('platform-risk-events')) return Response.json(page([]))
    return Response.json(page([]))
  }))
  render(<AccountsRiskPage api={new AdminApi({apiBaseUrl:'http://api',adminToken:'t',actorId:'a'})}/>)
  expect(await screen.findByText('账号一')).toBeInTheDocument()
  expect(screen.queryByText('secret://must-not-render')).not.toBeInTheDocument()
  expect(screen.queryByText('profile-secret')).not.toBeInTheDocument()
})

it('allows an editor to resolve a risk event through the existing backend endpoint', async()=>{
  const calls: Array<{url:string;init:RequestInit}> = []
  vi.stubGlobal('fetch',vi.fn(async(url:string|URL|Request,init:RequestInit={})=>{
    calls.push({url:String(url),init})
    const path=String(url)
    if(path.includes('platform-accounts')) return Response.json(page([]))
    if(path.includes('connector-instances')) return Response.json(page([]))
    if(path.includes('platform-risk-events') && (!init.method || init.method==='GET')) return Response.json(page([{id:'r1',connector_instance_id:'i1',platform_account_id:null,connector_run_id:null,platform:'test',risk_type:'rate_limit',risk_level:'R2',message:'触发频率限制',action_taken:'paused',manual_review_required:true,created_at:'2026-08-12T00:00:00Z',resolved_at:null,resolution_note:null}]))
    return Response.json({id:'r1'})
  }))
  render(<AccountsRiskPage api={new AdminApi({apiBaseUrl:'http://api',adminToken:'t',actorId:'a'})}/>)
  await userEvent.click(await screen.findByRole('button',{name:'处理风险事件'}))
  await userEvent.type(screen.getByLabelText('风险处理说明'),'已确认并解除限制')
  await userEvent.click(screen.getByRole('button',{name:'标记为已解决'}))
  expect(calls.some(call=>call.url.endsWith('/platform-risk-events/r1/resolve')&&call.init.method==='POST')).toBe(true)
})

it('creates a platform account for a connector instance without exposing credential values afterwards', async()=>{
  const calls:Array<{url:string;init:RequestInit}>=[]
  const instance={id:'i1',definition_id:'d1',connector_type:'mediacrawler',platform:'bilibili',name:'B站实例',enabled:true,status:'active',config:{},config_version:1}
  vi.stubGlobal('fetch',vi.fn(async(url:string|URL|Request,init:RequestInit={})=>{
    const path=String(url);calls.push({url:path,init})
    if(path.includes('connector-instances')) return Response.json(page([instance]))
    if(path.includes('platform-risk-events')) return Response.json(page([]))
    if(path.includes('platform-accounts')&&(!init.method||init.method==='GET')) return Response.json(page([]))
    if(path.endsWith('/platform-accounts')&&init.method==='POST') return Response.json({id:'a-new'})
    return Response.json({})
  }))
  render(<AccountsRiskPage api={new AdminApi({apiBaseUrl:'http://api',adminToken:'t',actorId:'editor'})}/>)
  const [createButton]=await screen.findAllByRole('button',{name:'新增平台账号'})
  await userEvent.click(createButton)
  await userEvent.type(screen.getByPlaceholderText('例如：B站采集账号 A'),'B站采集账号 A')
  await userEvent.type(screen.getByPlaceholderText('平台内稳定账号标识；创建后不修改'),'tester-01')
  await userEvent.type(screen.getByPlaceholderText('例如环境变量或凭据存储引用'),'bilibili-account-a')
  await userEvent.type(screen.getByPlaceholderText('可选，按运行环境的浏览器配置引用填写'),'profile-a')
  await userEvent.click(screen.getByRole('button',{name:'创建平台账号'}))
  const request=calls.find(call=>call.url.endsWith('/platform-accounts')&&call.init.method==='POST')
  expect(JSON.parse(String(request?.init.body))).toMatchObject({connector_instance_id:'i1',platform:'bilibili',display_name:'B站采集账号 A',account_identifier:'tester-01',credential_ref:'bilibili-account-a',browser_profile_ref:'profile-a'})
})

it('opens the dedicated browser workflow and starts the local runtime through the backend', async()=>{
  const calls:Array<{url:string;init:RequestInit}>=[]
  const account={id:'a1',connector_instance_id:'i1',platform:'bilibili',display_name:'B站采集账号',account_identifier:'tester',status:'healthy',manual_review_required:false,cooldown_until:null,risk_level:'R0',credential_configured:false,browser_profile_configured:true}
  const runtime={status:'STOPPED',enabled:true,browser_name:'Google Chrome',cdp_ready:false,managed_by_api:false,profile_configured:true,profile_ready:false,can_start:true,can_stop:false,can_open_login:false,cdp_host:'127.0.0.1',cdp_port:9222,message:'专用浏览器尚未启动。'}
  vi.stubGlobal('fetch',vi.fn(async(url:string|URL|Request,init:RequestInit={})=>{
    const path=String(url);calls.push({url:path,init})
    if(path.endsWith('/platform-accounts/a1/browser-runtime')&&(!init.method||init.method==='GET')) return Response.json(runtime)
    if(path.endsWith('/platform-accounts/a1/browser-runtime/start')&&init.method==='POST') return Response.json({...runtime,status:'RUNNING',cdp_ready:true,managed_by_api:true,can_start:false,can_stop:true,can_open_login:true,message:'专用浏览器已启动。'})
    if(path.includes('connector-instances')) return Response.json(page([{id:'i1',definition_id:'d1',connector_type:'mediacrawler',platform:'bilibili',name:'B站实例',enabled:true,status:'active',config:{},config_version:1}]))
    if(path.includes('platform-risk-events')) return Response.json(page([]))
    if(path.endsWith('/platform-accounts?page_size=100')) return Response.json(page([account]))
    return Response.json({})
  }))
  render(<AccountsRiskPage api={new AdminApi({apiBaseUrl:'http://api',adminToken:'t',actorId:'editor'})}/>)
  await userEvent.click(await screen.findByRole('button',{name:'浏览器环境'}))
  expect(await screen.findByText('专用浏览器未启动')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button',{name:'启动专用浏览器'}))
  expect(calls.some(call=>call.url.endsWith('/platform-accounts/a1/browser-runtime/start')&&call.init.method==='POST')).toBe(true)
  expect(await screen.findByText('专用浏览器已就绪')).toBeInTheDocument()
})
