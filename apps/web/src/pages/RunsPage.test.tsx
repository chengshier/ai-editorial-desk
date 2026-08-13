import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AdminApi } from '../api'
import { RunsPage } from './RunsPage'

const run={id:'12345678-1234-1234-1234-123456789012',connector_instance_id:'i1',source_id:'s1',parent_run_id:null,trigger_type:'retry',mode:'feed',status:'failed',started_at:'2026-08-07T01:00:00Z',progress_updated_at:'2026-08-07T01:00:05Z',finished_at:'2026-08-07T01:00:05Z',requested_limit:10,collected_count:2,inserted_count:1,duplicate_count:1,failed_count:1,retry_count:1,error_code:'request_timeout',error_message:'请求超时',checkpoint_before:{etag:'a'},checkpoint_after:null,budget:{actual_items:2},risk_action:null,metadata:{},latency_seconds:5,created_at:'2026-08-07T01:00:00Z'}

it('opens run detail and sends failed runs back to collection preflight', async()=>{
 const navigate=vi.fn()
 vi.stubGlobal('fetch',vi.fn(async(url:string|URL|Request)=>Response.json(String(url).endsWith(run.id)?run:{items:[run],page:1,page_size:20,total:1,has_next:false})))
 render(<RunsPage api={new AdminApi({apiBaseUrl:'http://api',adminToken:'t',actorId:'a'})} onNavigate={navigate}/>)
 await userEvent.click(await screen.findByText('12345678'))
 expect(await screen.findByText(/请求超时/)).toBeInTheDocument()
 expect(screen.getByText('运行前检查点')).toBeInTheDocument()
 expect(screen.queryByRole('button',{name:'人工重试'})).not.toBeInTheDocument()
 await userEvent.click(screen.getByRole('button',{name:'重新执行采集前检查'}))
 expect(navigate).toHaveBeenCalledWith('sources')
})

it('does not expose blind retry when a generic execution failure has no safe diagnosis', async()=>{
 const generic={...run,error_code:'collector_execution_failed',error_message:'采集执行失败'}
 vi.stubGlobal('fetch',vi.fn(async(url:string|URL|Request)=>Response.json(String(url).endsWith(generic.id)?generic:{items:[generic],page:1,page_size:20,total:1,has_next:false})))
 render(<RunsPage api={new AdminApi({apiBaseUrl:'http://api',adminToken:'t',actorId:'a'})} onNavigate={vi.fn()}/>)
 await userEvent.click(await screen.findByText('12345678'))
 expect(await screen.findByText('未获得可细分安全诊断')).toBeInTheDocument()
 expect(screen.queryByRole('button',{name:'人工重试'})).not.toBeInTheDocument()
 expect(screen.getByRole('button',{name:'重新执行采集前检查'})).toBeInTheDocument()
})

it('shows safe subprocess diagnosis before raw checkpoint details', async()=>{
 const diagnosed={...run,id:'87654321-1234-1234-1234-123456789012',mode:'search',error_code:'AUTH_REQUIRED',error_message:'MediaCrawler authentication is required',metadata:{subprocess_diagnostic:{failure_category:'AUTH',failure_code:'AUTH_REQUIRED',safe_message:'MediaCrawler authentication is required',runtime_stage:'login_state',auth_required:true},budget:{completed:true,actual_items:0}}}
 vi.stubGlobal('fetch',vi.fn(async(url:string|URL|Request)=>Response.json(String(url).endsWith(diagnosed.id)?diagnosed:{items:[diagnosed],page:1,page_size:20,total:1,has_next:false})))
 render(<RunsPage api={new AdminApi({apiBaseUrl:'http://api',adminToken:'t',actorId:'a'})} onNavigate={vi.fn()}/>)
 await userEvent.click(await screen.findByText('87654321'))
 expect(await screen.findByText(/失败诊断 · 登录 \/ 认证/)).toBeInTheDocument()
 expect(screen.getByText(/发生阶段：检查登录状态/)).toBeInTheDocument()
 expect(screen.getByText(/检查平台账号与浏览器登录态/)).toBeInTheDocument()
})
