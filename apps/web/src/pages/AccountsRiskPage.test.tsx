import { render, screen } from '@testing-library/react'
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
