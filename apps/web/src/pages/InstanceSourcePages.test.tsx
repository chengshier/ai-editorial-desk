import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AdminApi } from '../api'
import { InstancesPage } from './InstancesPage'
import { SourcesPage } from './SourcesPage'

const page = <T,>(items: T[]) => ({ items, page: 1, page_size: 100, total: items.length, has_next: false })

const definition = {
  id: 'def1',
  display_name: 'RSS / Atom',
  connector_type: 'rss',
  platform: 'rss',
  registered: true,
  implemented: true,
  enabled: true,
  validated: false,
  implementation_version: '0.1.0',
  capabilities: {},
  config_schema: { type: 'object', properties: {} },
  ui_schema: {},
}
const instance = {
  id: 'i1',
  definition_id: 'def1',
  name: 'RSS 实例',
  enabled: true,
  status: 'active',
  config: {},
  config_version: 1,
}
const source = {
  id: 'src1',
  connector_instance_id: 'i1',
  name: 'RSS Source',
  source_type: 'rss',
  mode: 'feed',
  scope_key: 'feed:one',
  external_ref: 'https://example.com/feed.xml',
  config: {},
  enabled: true,
  status: 'active',
}

function apiWithCalls(calls: Array<{ path: string; init: RequestInit }>): AdminApi {
  vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request, init: RequestInit = {}) => {
    const path = String(url)
    calls.push({ path, init })
    if (path.includes('/connector-definitions')) {
      return Response.json(page([definition]))
    }
    if (path.includes('/connector-instances') && (!init.method || init.method === 'GET')) {
      return Response.json(page([instance]))
    }
    if (path.includes('/sources') && (!init.method || init.method === 'GET')) {
      return Response.json(page([source]))
    }
    if (path.includes('/test-runs')) {
      return Response.json({ run_id: 'run1', status: 'succeeded' })
    }
    return Response.json({ id: 'ok' })
  }))
  return new AdminApi({ apiBaseUrl: 'http://api', adminToken: 'token', actorId: 'twelve' })
}

it('edits an instance and exposes both Test Run and Run Now through the runtime endpoint', async () => {
  const calls: Array<{ path: string; init: RequestInit }> = []
  render(<InstancesPage api={apiWithCalls(calls)} />)

  await screen.findByText('RSS 实例')
  await userEvent.click(screen.getByRole('button', { name: '编辑' }))
  const name = screen.getByLabelText('实例名称')
  await userEvent.clear(name)
  await userEvent.type(name, 'RSS 实例新版')
  await userEvent.click(screen.getByRole('button', { name: '保存修改' }))
  await userEvent.click(screen.getByRole('button', { name: 'Test Run' }))
  await userEvent.click(screen.getByRole('button', { name: 'Run Now' }))

  expect(calls.some(({ path, init }) => path.endsWith('/connector-instances/i1') && init.method === 'PATCH')).toBe(true)
  const runBodies = calls
    .filter(({ path }) => path.endsWith('/connector-instances/i1/test-runs'))
    .map(({ init }) => JSON.parse(String(init.body)) as { dry_run: boolean })
  expect(runBodies).toEqual(expect.arrayContaining([
    expect.objectContaining({ dry_run: true }),
    expect.objectContaining({ dry_run: false }),
  ]))
  expect(calls.filter(({ init }) => init.method && init.method !== 'GET').every(({ init }) => new Headers(init.headers).get('X-Actor-ID') === 'twelve')).toBe(true)
})

it('edits a Source and runs a dry Test Run without exposing secret fields', async () => {
  const calls: Array<{ path: string; init: RequestInit }> = []
  render(<SourcesPage api={apiWithCalls(calls)} />)

  await screen.findByText('RSS Source')
  expect(screen.queryByText(/credential_ref|browser_profile_ref|Authorization|Cookie|Token/i)).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: '编辑' }))
  const name = screen.getByLabelText('名称')
  await userEvent.clear(name)
  await userEvent.type(name, 'RSS Source 新版')
  await userEvent.click(screen.getByRole('button', { name: '保存修改' }))
  await userEvent.click(screen.getByRole('button', { name: 'Test Run' }))

  expect(calls.some(({ path, init }) => path.endsWith('/sources/src1') && init.method === 'PATCH')).toBe(true)
  const testRun = calls.find(({ path }) => path.endsWith('/connector-instances/i1/test-runs'))
  expect(testRun).toBeDefined()
  expect(JSON.parse(String(testRun?.init.body))).toMatchObject({ source_id: 'src1', requested_limit: 5, dry_run: true })
})
