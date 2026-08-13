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
  capabilities: { requires_account: false },
  config_schema: { type: 'object', properties: {} },
  ui_schema: {},
}
const instance = {
  id: 'i1',
  definition_id: 'def1',
  connector_type: 'rss',
  platform: 'rss',
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
    if (path.includes('/connector-definitions')) return Response.json(page([definition]))
    if (path.includes('/connector-instances') && (!init.method || init.method === 'GET')) return Response.json(page([instance]))
    if (path.includes('/sources') && (!init.method || init.method === 'GET')) return Response.json(page([source]))
    if (path.includes('/platform-accounts')) return Response.json(page([]))
    if (path.includes('/test-runs')) return Response.json({ run_id: 'run1', status: 'succeeded' })
    return Response.json({ id: 'ok' })
  }))
  return new AdminApi({ apiBaseUrl: 'http://api', adminToken: 'token', actorId: 'twelve' })
}

it('edits an instance and exposes both localized test and real run actions through the runtime endpoint', async () => {
  const calls: Array<{ path: string; init: RequestInit }> = []
  render(<InstancesPage api={apiWithCalls(calls)} />)

  await screen.findByText('RSS 实例')
  await userEvent.click(screen.getByRole('button', { name: '编辑' }))
  const name = screen.getByLabelText('实例名称')
  await userEvent.clear(name)
  await userEvent.type(name, 'RSS 实例新版')
  await userEvent.click(screen.getByRole('button', { name: '保存修改' }))

  await userEvent.click(screen.getByRole('button', { name: '测试运行' }))
  await userEvent.click(screen.getByRole('button', { name: '开始测试运行' }))
  await userEvent.click(screen.getByRole('button', { name: '立即执行' }))
  await userEvent.click(screen.getByRole('button', { name: '开始执行' }))

  expect(calls.some(({ path, init }) => path.endsWith('/connector-instances/i1') && init.method === 'PATCH')).toBe(true)
  const runBodies = calls
    .filter(({ path }) => path.endsWith('/connector-instances/i1/test-runs'))
    .map(({ init }) => JSON.parse(String(init.body)) as { dry_run: boolean })
  expect(runBodies).toEqual(expect.arrayContaining([
    expect.objectContaining({ dry_run: true, platform_account_id: null }),
    expect.objectContaining({ dry_run: false, platform_account_id: null }),
  ]))
  expect(calls.filter(({ init }) => init.method && init.method !== 'GET').every(({ init }) => new Headers(init.headers).get('X-Actor-ID') === 'twelve')).toBe(true)
})

it('edits a source and runs a dry test without exposing secret fields', async () => {
  const calls: Array<{ path: string; init: RequestInit }> = []
  render(<SourcesPage api={apiWithCalls(calls)} />)

  await screen.findByText('RSS Source')
  expect(screen.queryByText(/credential_ref|browser_profile_ref|Authorization|Cookie|Token/i)).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: '编辑' }))
  const name = screen.getByLabelText('信源名称')
  await userEvent.clear(name)
  await userEvent.type(name, 'RSS Source 新版')
  await userEvent.click(screen.getByRole('button', { name: '保存修改' }))
  await userEvent.click(screen.getByRole('button', { name: '测试运行' }))
  await userEvent.click(screen.getByRole('button', { name: '开始测试运行' }))

  expect(calls.some(({ path, init }) => path.endsWith('/sources/src1') && init.method === 'PATCH')).toBe(true)
  const testRun = calls.find(({ path }) => path.endsWith('/connector-instances/i1/test-runs'))
  expect(testRun).toBeDefined()
  expect(JSON.parse(String(testRun?.init.body))).toMatchObject({ source_id: 'src1', platform_account_id: null, requested_limit: 5, dry_run: true })
})

it('shows a run result and offers the next navigation step after an instance run', async () => {
  const calls: Array<{ path: string; init: RequestInit }> = []
  const onNavigate = vi.fn()
  render(<InstancesPage api={apiWithCalls(calls)} onNavigate={onNavigate}/>)

  await userEvent.click(await screen.findByRole('button', { name: '测试运行' }))
  await userEvent.click(screen.getByRole('button', { name: '开始测试运行' }))
  expect(await screen.findByText(/测试运行已创建：succeeded \/ run1/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '查看运行记录' }))
  expect(onNavigate).toHaveBeenCalledWith('runs')
})

it('shows a run result and offers the next navigation step after a source test', async () => {
  const calls: Array<{ path: string; init: RequestInit }> = []
  const onNavigate = vi.fn()
  render(<SourcesPage api={apiWithCalls(calls)} onNavigate={onNavigate}/>)

  await userEvent.click(await screen.findByRole('button', { name: '测试运行' }))
  await userEvent.click(screen.getByRole('button', { name: '开始测试运行' }))
  expect(await screen.findByText(/测试运行已创建：succeeded \/ run1/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '查看运行记录' }))
  expect(onNavigate).toHaveBeenCalledWith('runs')
})

it('requires and forwards a same-instance platform account for MediaCrawler test runs', async () => {
  const calls: Array<{ path: string; init: RequestInit }> = []
  const mediaDefinition = { ...definition, id: 'def-media', display_name: 'B站', connector_type: 'mediacrawler', platform: 'bilibili', capabilities: { requires_account: true } }
  const mediaInstance = { ...instance, id: 'media-i', definition_id: 'def-media', connector_type: 'mediacrawler', platform: 'bilibili', name: 'B站实例' }
  const mediaSource = { ...source, id: 'media-src', connector_instance_id: 'media-i', name: 'B站热点', source_type: 'mediacrawler', mode: 'search' }
  const account = { id:'acc1', connector_instance_id:'media-i', platform:'bilibili', display_name:'B站测试账号', account_identifier:'tester', status:'healthy', manual_review_required:false, credential_configured:true, browser_profile_configured:true }
  vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request, init: RequestInit = {}) => {
    const path = String(url)
    calls.push({ path, init })
    if (path.includes('/connector-definitions')) return Response.json(page([mediaDefinition]))
    if (path.includes('/connector-instances') && (!init.method || init.method === 'GET')) return Response.json(page([mediaInstance]))
    if (path.includes('/sources') && (!init.method || init.method === 'GET')) return Response.json(page([mediaSource]))
    if (path.includes('/platform-accounts')) return Response.json(page([account]))
    if (path.includes('/test-runs')) return Response.json({ run_id: 'run-media', status: 'succeeded' })
    return Response.json({ id: 'ok' })
  }))

  render(<InstancesPage api={new AdminApi({ apiBaseUrl: 'http://api', adminToken: 'token', actorId: 'twelve' })}/>)
  await userEvent.click(await screen.findByRole('button', { name: '测试运行' }))
  expect(screen.getByRole('combobox', { name: '平台账号' })).toHaveValue('acc1')
  await userEvent.click(screen.getByRole('button', { name: '开始测试运行' }))

  const request = calls.find(({ path }) => path.endsWith('/connector-instances/media-i/test-runs'))
  expect(JSON.parse(String(request?.init.body))).toMatchObject({ source_id: 'media-src', platform_account_id: 'acc1', dry_run: true })
})
