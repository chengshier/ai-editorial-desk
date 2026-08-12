import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AdminApi } from '../api'
import { AccountsRiskPage } from './AccountsRiskPage'

it('does not render sensitive credential values returned accidentally by an API', async()=>{
  vi.stubGlobal('fetch',vi.fn(async(url:string|URL|Request)=>{
    const path=String(url)
    const payload=path.includes('platform-accounts')?{items:[{id:'a1',connector_instance_id:'i1',platform:'test',display_name:'账号一',status:'healthy',manual_review_required:false,cooldown_until:null,credential_ref:'secret://must-not-render',browser_profile_ref:'profile-secret'}],page:1,page_size:20,total:1,has_next:false}:{items:[],page:1,page_size:20,total:0,has_next:false}
    return new Response(JSON.stringify(payload),{status:200,headers:{'Content-Type':'application/json'}})
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
    if(path.includes('platform-accounts')) return Response.json({items:[],page:1,page_size:20,total:0,has_next:false})
    if(path.includes('platform-risk-events') && (!init.method || init.method==='GET')) return Response.json({items:[{id:'r1',connector_instance_id:'i1',platform_account_id:null,connector_run_id:null,platform:'test',risk_type:'rate_limit',risk_level:'R2',message:'触发频率限制',action_taken:'paused',manual_review_required:true,created_at:'2026-08-12T00:00:00Z',resolved_at:null,resolution_note:null}],page:1,page_size:20,total:1,has_next:false})
    return Response.json({id:'r1'})
  }))
  render(<AccountsRiskPage api={new AdminApi({apiBaseUrl:'http://api',adminToken:'t',actorId:'a'})}/>)
  await userEvent.click(await screen.findByRole('button',{name:'处理风险事件'}))
  await userEvent.type(screen.getByLabelText('风险处理说明'),'已确认并解除限制')
  await userEvent.click(screen.getByRole('button',{name:'标记为已解决'}))
  expect(calls.some(call=>call.url.endsWith('/platform-risk-events/r1/resolve')&&call.init.method==='POST')).toBe(true)
})
