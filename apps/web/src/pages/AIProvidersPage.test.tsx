import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AdminApi } from '../api'
import { AIProvidersPage } from './AIProvidersPage'

const emptyPage = { items: [], page: 1, page_size: 100, total: 0, has_next: false }

it('sends the selected structured output mode in model config', async () => {
  const bodies: unknown[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request, init: RequestInit = {}) => {
    const path = String(url)
    if (!init.method || init.method === 'GET') {
      if (path.includes('/ai/providers')) {
        return new Response(JSON.stringify({
          ...emptyPage,
          items: [{ id: 'provider-1', provider_key: 'provider', display_name: 'Provider', provider_type: 'openai_compatible', base_url: 'https://provider.test/v1', credential_configured: false, credential_ref_masked: null, enabled: false, validation_status: 'NOT_TESTED', last_validated_at: null, timeout_seconds: 30, max_concurrency: 1, retry_limit: 0, config: {}, model_count: 0, last_invocation_at: null, error_rate: null, created_at: '2026-08-11T00:00:00Z', updated_at: '2026-08-11T00:00:00Z' }],
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
  await userEvent.selectOptions(screen.getByLabelText('所属服务商'), 'provider-1')
  await userEvent.type(screen.getByLabelText('模型标识'), 'structured-model')
  await userEvent.type(screen.getByLabelText('服务商模型名称'), 'vendor-model')
  await userEvent.selectOptions(screen.getByLabelText('结构化输出方式'), 'json_object')
  await userEvent.click(screen.getByRole('button', { name: '创建模型' }))
  expect(bodies).toContainEqual(expect.objectContaining({
    config: { structured_output_mode: 'json_object' },
  }))
})
