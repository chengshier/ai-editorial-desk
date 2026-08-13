import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AdminApi } from '../api'
import { AIProvidersPage } from './AIProvidersPage'

const emptyPage = { items: [], page: 1, page_size: 100, total: 0, has_next: false }
const providerFixture = { id: 'provider-1', provider_key: 'provider', display_name: 'Provider', provider_type: 'openai_compatible', base_url: 'https://provider.test/v1', credential_configured: false, credential_ref_masked: null, enabled: false, validation_status: 'NOT_TESTED', last_validated_at: null, timeout_seconds: 30, max_concurrency: 1, retry_limit: 0, config: {}, model_count: 0, last_invocation_at: null, error_rate: null, created_at: '2026-08-11T00:00:00Z', updated_at: '2026-08-11T00:00:00Z' }

it('sends the selected structured output mode in model config', async () => {
  const bodies: unknown[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request, init: RequestInit = {}) => {
    const path = String(url)
    if (!init.method || init.method === 'GET') {
      if (path.includes('/ai/providers')) {
        return new Response(JSON.stringify({
          ...emptyPage,
          items: [providerFixture],
        }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      return new Response(JSON.stringify(emptyPage), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    bodies.push(JSON.parse(String(init.body)))
    return new Response(JSON.stringify({ id: 'model-1' }), { status: 201, headers: { 'Content-Type': 'application/json' } })
  }))
  const api = new AdminApi({ apiBaseUrl: 'http://api', adminToken: 'token', actorId: 'human' })
  render(<AIProvidersPage api={api} />)
  await screen.findByText('Provider')
  await userEvent.click(screen.getAllByRole('button', { name: '新建模型' })[0])
  await userEvent.selectOptions(screen.getByLabelText('所属服务商'), 'provider-1')
  await userEvent.type(screen.getByLabelText('模型标识'), 'structured-model')
  await userEvent.type(screen.getByLabelText('服务商模型名称'), 'vendor-model')
  await userEvent.selectOptions(screen.getByLabelText('结构化输出方式'), 'json_object')
  await userEvent.click(screen.getByRole('button', { name: '创建模型' }))
  expect(bodies).toContainEqual(expect.objectContaining({
    config: { structured_output_mode: 'json_object' },
  }))
})

it('shows and updates an existing provider base url', async () => {
  const patchBodies: unknown[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request, init: RequestInit = {}) => {
    const path = String(url)
    if (!init.method || init.method === 'GET') {
      if (path.includes('/ai/providers')) return new Response(JSON.stringify({ ...emptyPage, items: [providerFixture] }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      return new Response(JSON.stringify(emptyPage), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    if (init.method === 'PATCH' && path.includes('/ai/providers/provider-1')) {
      patchBodies.push(JSON.parse(String(init.body)))
      return new Response(JSON.stringify({ ...providerFixture, base_url: 'https://new-provider.test/v1' }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  const api = new AdminApi({ apiBaseUrl: 'http://api', adminToken: 'token', actorId: 'human' })
  render(<AIProvidersPage api={api} />)
  await screen.findByText('https://provider.test/v1')
  await userEvent.click(screen.getByRole('button', { name: '编辑连接' }))
  const input = screen.getByLabelText(/^服务地址（Base URL）/)
  await userEvent.clear(input)
  await userEvent.type(input, 'https://new-provider.test/v1')
  await userEvent.click(screen.getByRole('button', { name: '保存连接信息' }))
  expect(patchBodies).toContainEqual(expect.objectContaining({ base_url: 'https://new-provider.test/v1' }))
})

it('explains DeepSeek INVALID_REQUEST when json schema mode is selected', async () => {
  const deepseekProvider = {
    ...providerFixture,
    provider_key: 'deepseek-production',
    display_name: 'DeepSeek Production',
    base_url: 'https://api.deepseek.com',
    credential_configured: true,
    credential_ref_masked: 'env://***',
    enabled: true,
  }
  const model = {
    id: 'model-1', provider_id: 'provider-1', model_key: 'deepseek-v4-flash', model_name: 'deepseek-v4-flash',
    capabilities: ['structured_output'], enabled: true, context_window: null, input_price_per_million: null,
    output_price_per_million: null, embedding_price_per_million: null, pricing_version: 'test', dimensions: null,
    config: { structured_output_mode: 'json_schema' }, created_at: '2026-08-11T00:00:00Z', updated_at: '2026-08-11T00:00:00Z',
  }
  vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request, init: RequestInit = {}) => {
    const path = String(url)
    if (!init.method || init.method === 'GET') {
      if (path.includes('/ai/providers')) return new Response(JSON.stringify({ ...emptyPage, items: [deepseekProvider] }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (path.includes('/ai/models')) return new Response(JSON.stringify({ ...emptyPage, items: [model] }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    if (init.method === 'POST' && path.includes('/ai/providers/provider-1/test')) {
      return new Response(JSON.stringify({ invocation_id: 'invocation-1', status: 'failed', error_code: 'INVALID_REQUEST' }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  const api = new AdminApi({ apiBaseUrl: 'http://api', adminToken: 'token', actorId: 'human' })
  render(<AIProvidersPage api={api} />)
  await screen.findByText('DeepSeek Production')
  await userEvent.click(screen.getByRole('button', { name: '连接测试' }))
  expect(await screen.findByText(/DeepSeek 的 JSON Output 使用 JSON Object/)).toBeInTheDocument()
  expect(screen.queryByText(/连接测试完成：failed/)).not.toBeInTheDocument()
})

it('edits an existing model structured output mode', async () => {
  const model = {
    id: 'model-1', provider_id: 'provider-1', model_key: 'structured-model', model_name: 'vendor-model',
    capabilities: ['structured_output'], enabled: true, context_window: null, input_price_per_million: null,
    output_price_per_million: null, embedding_price_per_million: null, pricing_version: 'test', dimensions: null,
    config: { structured_output_mode: 'json_schema', keep_me: true }, created_at: '2026-08-11T00:00:00Z', updated_at: '2026-08-11T00:00:00Z',
  }
  const patchBodies: unknown[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request, init: RequestInit = {}) => {
    const path = String(url)
    if (!init.method || init.method === 'GET') {
      if (path.includes('/ai/providers')) return new Response(JSON.stringify({ ...emptyPage, items: [providerFixture] }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (path.includes('/ai/models')) return new Response(JSON.stringify({ ...emptyPage, items: [model] }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    if (init.method === 'PATCH' && path.includes('/ai/models/model-1')) {
      patchBodies.push(JSON.parse(String(init.body)))
      return new Response(JSON.stringify({ ...model, config: { structured_output_mode: 'json_object', keep_me: true } }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  const api = new AdminApi({ apiBaseUrl: 'http://api', adminToken: 'token', actorId: 'human' })
  render(<AIProvidersPage api={api} />)
  await screen.findByText('structured-model')
  await userEvent.click(screen.getByRole('button', { name: '编辑模型' }))
  await userEvent.selectOptions(screen.getByLabelText('结构化输出方式'), 'json_object')
  await userEvent.click(screen.getByRole('button', { name: '保存模型配置' }))
  expect(patchBodies).toContainEqual(expect.objectContaining({
    config: { structured_output_mode: 'json_object', keep_me: true },
  }))
})
