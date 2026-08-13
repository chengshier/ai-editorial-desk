import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AdminApi } from '../api'
import { SchedulesPage } from './SchedulesPage'

const page = <T,>(items: T[]) => ({items,page:1,page_size:100,total:items.length,has_next:false})
const instance={id:'i1',definition_id:'def1',connector_type:'hotlist',platform:'hotlist',name:'百度实例',enabled:true,status:'active',config:{},config_version:1}
const definition={id:'def1',display_name:'国内公开热榜',connector_type:'hotlist',platform:'hotlist',registered:true,implemented:true,enabled:true,validated:true,implementation_version:'0.2.0',capabilities:{requires_account:false},config_schema:{},ui_schema:{}}

it('renders schedule state and sends actor header for pause', async () => {
  const calls: RequestInit[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request, init: RequestInit = {}) => {
    calls.push(init)
    const path=String(url)
    if(path.includes('/schedules') && (!init.method || init.method==='GET')) return Response.json(page([{id:'s1',connector_instance_id:'i1',source_id:'src1',platform_account_id:null,name:'百度低频',enabled:true,schedule_type:'interval',interval_seconds:900,timezone:'Asia/Shanghai',requested_limit:20,next_run_at:'2026-08-07T03:00:00Z',consecutive_failures:0}]))
    if(path.includes('/sources')) return Response.json(page([{id:'src1',connector_instance_id:'i1',name:'百度',source_type:'hotlist',mode:'hotlist',scope_key:'baidu',config:{},enabled:true,status:'active'}]))
    if(path.includes('/connector-instances')) return Response.json(page([instance]))
    if(path.includes('/connector-definitions')) return Response.json(page([definition]))
    if(path.includes('/platform-accounts')) return Response.json(page([]))
    return Response.json({id:'s1'})
  }))
  const api=new AdminApi({apiBaseUrl:'http://api',adminToken:'token',actorId:'twelve'})
  render(<SchedulesPage api={api}/>)
  await screen.findByText('百度低频')
  await userEvent.click(screen.getByRole('button',{name:'暂停'}))
  const actorHeaders=calls.map((call)=>new Headers(call.headers).get('X-Actor-ID')).filter(Boolean)
  expect(actorHeaders).toContain('twelve')
})

it('surfaces a schedule action failure instead of leaving the user without feedback', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request, init: RequestInit = {}) => {
    const path = String(url)
    if (path.includes('/schedules') && (!init.method || init.method === 'GET')) return Response.json(page([{id:'s1',connector_instance_id:'i1',source_id:'src1',platform_account_id:null,name:'百度低频',enabled:true,schedule_type:'interval',interval_seconds:900,timezone:'Asia/Shanghai',requested_limit:20,next_run_at:'2026-08-07T03:00:00Z',consecutive_failures:0}]))
    if (path.includes('/sources')) return Response.json(page([]))
    if (path.includes('/connector-instances')) return Response.json(page([instance]))
    if (path.includes('/connector-definitions')) return Response.json(page([definition]))
    if (path.includes('/platform-accounts')) return Response.json(page([]))
    if (path.includes('/schedules/s1/pause')) return new Response(JSON.stringify({ detail: '任务当前不能暂停' }), { status: 409, headers: { 'Content-Type': 'application/json' } })
    return Response.json({})
  }))
  render(<SchedulesPage api={new AdminApi({apiBaseUrl:'http://api',adminToken:'token',actorId:'twelve'})}/>)

  await userEvent.click(await screen.findByRole('button', { name: '暂停' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('任务当前不能暂停')
})

it('binds a healthy platform account when creating a MediaCrawler schedule', async () => {
  const calls: Array<{url:string;init:RequestInit}> = []
  const mediaInstance={...instance,id:'mi1',definition_id:'md1',connector_type:'mediacrawler',platform:'bilibili',name:'B站实例'}
  const mediaDefinition={...definition,id:'md1',display_name:'B站',connector_type:'mediacrawler',platform:'bilibili',capabilities:{requires_account:true}}
  const mediaSource={id:'ms1',connector_instance_id:'mi1',name:'B站热点',source_type:'mediacrawler',mode:'search',scope_key:'bilibili-tech',config:{},enabled:true,status:'active'}
  const account={id:'a1',connector_instance_id:'mi1',platform:'bilibili',display_name:'B站采集账号',account_identifier:'tester',status:'healthy',manual_review_required:false,credential_configured:true,browser_profile_configured:true}
  vi.stubGlobal('fetch',vi.fn(async(url:string|URL|Request,init:RequestInit={})=>{
    const path=String(url);calls.push({url:path,init})
    if(path.includes('/schedules')&&(!init.method||init.method==='GET')) return Response.json(page([]))
    if(path.includes('/sources')) return Response.json(page([mediaSource]))
    if(path.includes('/connector-instances')) return Response.json(page([mediaInstance]))
    if(path.includes('/connector-definitions')) return Response.json(page([mediaDefinition]))
    if(path.includes('/platform-accounts')) return Response.json(page([account]))
    if(path.endsWith('/schedules')&&init.method==='POST') return Response.json({id:'sched-new'})
    return Response.json({})
  }))
  render(<SchedulesPage api={new AdminApi({apiBaseUrl:'http://api',adminToken:'token',actorId:'twelve'})}/>)
  const [createButton]=await screen.findAllByRole('button',{name:'创建采集任务'})
  await userEvent.click(createButton)
  await userEvent.type(screen.getByPlaceholderText('例如：B站科技热点 · 每 15 分钟'),'B站测试任务')
  expect(screen.getByRole('combobox',{name:'平台账号'})).toHaveValue('a1')
  await userEvent.click(screen.getByRole('button',{name:'创建任务'}))
  const request=calls.find(call=>call.url.endsWith('/schedules')&&call.init.method==='POST')
  expect(JSON.parse(String(request?.init.body))).toMatchObject({source_id:'ms1',connector_instance_id:'mi1',platform_account_id:'a1'})
})
