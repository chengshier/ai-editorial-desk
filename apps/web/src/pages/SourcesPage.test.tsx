import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AdminApi } from '../api'
import { SourcesPage } from './SourcesPage'

const page=<T,>(items:T[])=>({items,page:1,page_size:100,total:items.length,has_next:false})
const definition={id:'definition-1',display_name:'B站',connector_type:'mediacrawler',platform:'bilibili',registered:true,implemented:true,enabled:true,validated:true,implementation_version:'mediacrawler-m2c-v1',capabilities:{search:true,account:true,detail:true,comments:true,requires_account:true,allowed_modes:['search','account','detail','comments']},config_schema:{type:'object',properties:{}},ui_schema:{}}
const instance={id:'instance-1',definition_id:'definition-1',connector_type:'mediacrawler',platform:'bilibili',name:'B站采集实例',enabled:true,status:'active',config:{modes:['search']},config_version:1}

it('derives source type and presents a mode-specific search target',async()=>{
 const bodies:unknown[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string|URL|Request,init:RequestInit={})=>{const path=String(url);if(init.method==='POST'&&path.endsWith('/sources')){bodies.push(JSON.parse(String(init.body)));return Response.json({id:'source-1'},{status:201})}if(path.includes('/connector-instances'))return Response.json(page([instance]));if(path.includes('/connector-definitions'))return Response.json(page([definition]));if(path.includes('/platform-accounts'))return Response.json(page([]));if(path.includes('/sources'))return Response.json(page([]));return Response.json(page([]))}))
 render(<SourcesPage api={new AdminApi({apiBaseUrl:'http://api',adminToken:'token',actorId:'editor'})}/>)
 await screen.findByText('暂无信源')
 await userEvent.click(screen.getAllByRole('button',{name:'新建信源'})[0])
 expect(screen.getByLabelText('连接器实例')).toHaveValue('instance-1')
 expect(screen.getByLabelText('采集模式')).toHaveValue('search')
 expect(screen.getByText(/一个搜索信源对应一个稳定关键词/)).toBeInTheDocument()
 await userEvent.type(screen.getByLabelText('信源名称'),'B站 AI Agent')
 await userEvent.type(screen.getByLabelText(/搜索关键词/),'AI Agent')
 await userEvent.click(screen.getByRole('button',{name:'保存信源'}))
 await waitFor(()=>expect(bodies).toHaveLength(1))
 expect(bodies[0]).toEqual(expect.objectContaining({connector_instance_id:'instance-1',source_type:'mediacrawler',mode:'search',scope_key:'search:AI Agent',external_ref:'AI Agent'}))
})

it('requires read-only preflight before exposing a real low-volume collection action',async()=>{
 const source={id:'source-1',connector_instance_id:'instance-1',name:'B站 AI',source_type:'mediacrawler',mode:'search',scope_key:'search:AI',external_ref:'AI',config:{},enabled:true,status:'active'}
 const account={id:'account-1',connector_instance_id:'instance-1',platform:'bilibili',display_name:'人工登录账号',account_identifier:'masked',status:'healthy',manual_review_required:false,credential_configured:false,browser_profile_configured:true}
 const calls:string[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string|URL|Request,init:RequestInit={})=>{const path=String(url);calls.push(`${init.method||'GET'} ${path}`);if(path.includes('collection-preflight')&&init.method==='POST')return Response.json({status:'READY',platform:'bilibili',mode:'search',requested_limit:1,comment_limit:0,initiates_platform_request:false,uses_local_cdp:true,account_label:'人工登录账号',checkpoint_summary:{resume_scope:'search:page:2'},budget_summary:{budget_count:1},checks:[{name:'cdp',status:'READY',message:'本地 Chrome CDP 可连接。'}]});if(path.includes('/connector-instances'))return Response.json(page([instance]));if(path.includes('/connector-definitions'))return Response.json(page([definition]));if(path.includes('/platform-accounts'))return Response.json(page([account]));if(path.includes('/sources'))return Response.json(page([source]));return Response.json(page([]))}))
 render(<SourcesPage api={new AdminApi({apiBaseUrl:'http://api',adminToken:'token',actorId:'editor'})}/>)
 await userEvent.click(await screen.findByRole('button',{name:'采集前检查'}))
 expect(screen.queryByRole('button',{name:'确认发起一次真实低量采集'})).not.toBeInTheDocument()
 await userEvent.click(screen.getByRole('button',{name:'执行采集前检查'}))
 expect(await screen.findByText(/READY · 可以进入人工确认/)).toBeInTheDocument()
 expect(screen.getByText(/search:page:2/)).toBeInTheDocument()
 expect(screen.getByRole('button',{name:'确认发起一次真实低量采集'})).toBeInTheDocument()
 expect(calls.some(value=>value.includes('collection-preflight'))).toBe(true)
})
