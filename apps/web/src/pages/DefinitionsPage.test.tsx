import { render, screen } from '@testing-library/react'
import { AdminApi } from '../api'
import { DefinitionsPage } from './DefinitionsPage'

it('shows registered implemented enabled validated independently', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({items:[{id:'d1',display_name:'百度热榜',connector_type:'hotlist',platform:'hotlist',registered:true,implemented:true,enabled:true,validated:false,implementation_version:'0.2.0',capabilities:{hotlist:true},config_schema:{type:'object'},ui_schema:{}}],page:1,page_size:20,total:1,has_next:false}),{status:200,headers:{'Content-Type':'application/json'}})))
  render(<DefinitionsPage api={new AdminApi({apiBaseUrl:'http://api',adminToken:'test-token',actorId:'actor'})}/>)
  expect(await screen.findByText('百度热榜')).toBeInTheDocument()
  expect(screen.getByText(/实现: 是/)).toBeInTheDocument()
  expect(screen.getByText(/验真: 否/)).toBeInTheDocument()
})
