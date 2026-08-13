import { afterEach, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { AdminApi } from '../api'
import { AIRoutesPage } from './AIRoutesPage'

afterEach(() => vi.unstubAllGlobals())

it('saves task-level max output tokens without replacing unrelated route config', async () => {
  let savedBody: Record<string, unknown> | null = null
  const route = {
    id: 'route-1', task_key: 'draft_generation', version: 1,
    primary_model_id: null, fallback_model_ids: [], timeout_seconds: 30, retry_limit: 1,
    budget_policy: { reserve_output_tokens: 512 },
    config: { max_retry_delay_seconds: 1, other: { keep: true } },
    enabled: true, is_active: true, created_at: '2026-08-13T00:00:00Z',
  }
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input); const method = init?.method || 'GET'
    if (url.includes('/api/v1/admin/ai/routes/draft_generation') && method === 'PUT') {
      savedBody = JSON.parse(String(init?.body)) as Record<string, unknown>
      return Response.json({ ...route, version: 2, config: (savedBody as { config: unknown }).config })
    }
    if (url.includes('/api/v1/admin/ai/routes')) return Response.json({ items: [route], page: 1, page_size: 100, total: 1, has_next: false })
    if (url.includes('/api/v1/admin/ai/models')) return Response.json({ items: [], page: 1, page_size: 100, total: 0, has_next: false })
    return new Response('not found', { status: 404 })
  }))

  render(<AIRoutesPage api={new AdminApi({ apiBaseUrl: 'http://api', adminToken: 'token', actorId: 'editor' })}/>)
  fireEvent.click(await screen.findByRole('button', { name: '配置路由' }))
  const input = await screen.findByLabelText('draft_generation 最大输出 Token')
  expect(input).toHaveAttribute('placeholder', '6000')
  fireEvent.change(input, { target: { value: '7000' } })
  fireEvent.click(screen.getByRole('button', { name: '保存为 v2' }))

  await waitFor(() => expect(savedBody).not.toBeNull())
  expect(savedBody).toMatchObject({
    config: {
      max_retry_delay_seconds: 1,
      other: { keep: true },
      generation_policy: { max_output_tokens: 7000 },
    },
  })
})

it('only exposes the token editor for controlled generation tasks', async () => {
  const routes = [
    { id:'route-evidence', task_key:'evidence_extraction', version:2, primary_model_id:null, fallback_model_ids:[], timeout_seconds:30, retry_limit:1, budget_policy:{}, config:{}, enabled:true, is_active:true, created_at:'2026-08-13T00:00:00Z' },
    { id:'route-embedding', task_key:'signal_embedding', version:1, primary_model_id:null, fallback_model_ids:[], timeout_seconds:30, retry_limit:1, budget_policy:{}, config:{}, enabled:true, is_active:true, created_at:'2026-08-13T00:00:00Z' },
  ]
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url=String(input)
    if(url.includes('/api/v1/admin/ai/routes')) return Response.json({items:routes,page:1,page_size:100,total:2,has_next:false})
    return Response.json({items:[],page:1,page_size:100,total:0,has_next:false})
  }))
  render(<AIRoutesPage api={new AdminApi({apiBaseUrl:'http://api',adminToken:'token',actorId:'editor'})}/>)
  const buttons=await screen.findAllByRole('button',{name:'配置路由'})
  fireEvent.click(buttons[0])
  expect(await screen.findByLabelText('evidence_extraction 最大输出 Token')).toHaveAttribute('placeholder','4096')
  fireEvent.click(screen.getByRole('button',{name:'取消'}))
  fireEvent.click(buttons[1])
  expect(screen.queryByLabelText('signal_embedding 最大输出 Token')).not.toBeInTheDocument()
})
