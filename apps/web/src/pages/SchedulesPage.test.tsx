import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AdminApi } from '../api'
import { SchedulesPage } from './SchedulesPage'

it('renders schedule state and sends actor header for pause', async () => {
  const calls: RequestInit[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request, init: RequestInit = {}) => {
    calls.push(init)
    const path=String(url)
    if(path.includes('/schedules') && (!init.method || init.method==='GET')) return new Response(JSON.stringify({items:[{id:'s1',connector_instance_id:'i1',source_id:'src1',name:'百度低频',enabled:true,schedule_type:'interval',interval_seconds:900,timezone:'Asia/Shanghai',requested_limit:20,next_run_at:'2026-08-07T03:00:00Z',consecutive_failures:0}],page:1,page_size:20,total:1,has_next:false}),{status:200,headers:{'Content-Type':'application/json'}})
    if(path.includes('/sources')) return new Response(JSON.stringify({items:[{id:'src1',connector_instance_id:'i1',name:'百度',source_type:'hotlist',mode:'hotlist',scope_key:'baidu',config:{},enabled:true,status:'active'}],page:1,page_size:20,total:1,has_next:false}),{status:200,headers:{'Content-Type':'application/json'}})
    return new Response(JSON.stringify({id:'s1'}),{status:200,headers:{'Content-Type':'application/json'}})
  }))
  const api=new AdminApi({apiBaseUrl:'http://api',adminToken:'token',actorId:'twelve'})
  render(<SchedulesPage api={api}/>)
  await screen.findByText('百度低频')
  await userEvent.click(screen.getByRole('button',{name:'暂停'}))
  const actorHeaders=calls.map((call)=>new Headers(call.headers).get('X-Actor-ID')).filter(Boolean)
  expect(actorHeaders).toContain('twelve')
})
