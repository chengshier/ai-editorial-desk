import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AdminApi } from '../api'
import { RunsPage } from './RunsPage'

const run={id:'12345678-1234-1234-1234-123456789012',connector_instance_id:'i1',source_id:'s1',parent_run_id:null,trigger_type:'retry',mode:'feed',status:'failed',started_at:'2026-08-07T01:00:00Z',progress_updated_at:'2026-08-07T01:00:05Z',finished_at:'2026-08-07T01:00:05Z',requested_limit:10,collected_count:2,inserted_count:1,duplicate_count:1,failed_count:1,retry_count:1,error_code:'request_timeout',error_message:'请求超时',checkpoint_before:{etag:'a'},checkpoint_after:null,budget:{actual_items:2},risk_action:null,metadata:{},latency_seconds:5,created_at:'2026-08-07T01:00:00Z'}

it('opens run detail with checkpoint, budget and retry action', async()=>{
  vi.stubGlobal('fetch',vi.fn(async(url:string|URL|Request)=>new Response(JSON.stringify(String(url).endsWith(run.id)?run:{items:[run],page:1,page_size:20,total:1,has_next:false}),{status:200,headers:{'Content-Type':'application/json'}})))
  render(<RunsPage api={new AdminApi({apiBaseUrl:'http://api',adminToken:'t',actorId:'a'})}/>)
  await userEvent.click(await screen.findByText('12345678'))
  expect(await screen.findByText(/请求超时/)).toBeInTheDocument()
  expect(screen.getByText('运行前检查点')).toBeInTheDocument()
  expect(screen.getByRole('button',{name:'人工重试'})).toBeInTheDocument()
})

it('surfaces retry failures and disables duplicate submission while retry is pending', async()=>{
  let rejectRetry: ((reason?: unknown) => void) | undefined
  vi.stubGlobal('fetch',vi.fn(async(url:string|URL|Request)=>{
    const path=String(url)
    if(path.endsWith(run.id)) return Response.json(run)
    if(path.endsWith('/retry')) return await new Promise<Response>((_, reject) => { rejectRetry=reject })
    return Response.json({items:[run],page:1,page_size:20,total:1,has_next:false})
  }))
  render(<RunsPage api={new AdminApi({apiBaseUrl:'http://api',adminToken:'t',actorId:'a'})}/>)
  await userEvent.click(await screen.findByText('12345678'))
  const retry = await screen.findByRole('button',{name:'人工重试'})
  await userEvent.click(retry)
  expect(retry).toBeDisabled()
  rejectRetry?.(new Error('重试服务不可用'))
  expect(await screen.findByRole('alert')).toHaveTextContent('重试服务不可用')
})
