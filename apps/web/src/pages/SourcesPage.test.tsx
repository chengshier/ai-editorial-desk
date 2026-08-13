import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AdminApi } from '../api'
import { SourcesPage } from './SourcesPage'

const page = <T,>(items: T[]) => ({ items, page: 1, page_size: 100, total: items.length, has_next: false })
const definition = {
  id: 'definition-1', display_name: 'B站', connector_type: 'mediacrawler', platform: 'bilibili',
  registered: true, implemented: true, enabled: true, validated: true, implementation_version: 'mediacrawler-m2c-v1',
  capabilities: { search: true, account: true, detail: true, comments: true, requires_account: true, allowed_modes: ['search', 'account', 'detail', 'comments'] },
  config_schema: { type: 'object', properties: {} }, ui_schema: {},
}
const instance = { id: 'instance-1', definition_id: 'definition-1', connector_type: 'mediacrawler', platform: 'bilibili', name: 'B站采集实例', enabled: true, status: 'active', config: { modes: ['search'] }, config_version: 1 }

it('derives source type and presents a mode-specific search target', async () => {
  const bodies: unknown[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request, init: RequestInit = {}) => {
    const path = String(url)
    if (init.method === 'POST' && path.endsWith('/sources')) {
      bodies.push(JSON.parse(String(init.body)))
      return Response.json({ id: 'source-1' }, { status: 201 })
    }
    if (path.includes('/connector-instances')) return Response.json(page([instance]))
    if (path.includes('/connector-definitions')) return Response.json(page([definition]))
    if (path.includes('/platform-accounts')) return Response.json(page([]))
    if (path.includes('/sources')) return Response.json(page([]))
    return Response.json(page([]))
  }))

  render(<SourcesPage api={new AdminApi({ apiBaseUrl: 'http://api', adminToken: 'token', actorId: 'editor' })} />)
  await screen.findByText('暂无信源')
  await userEvent.click(screen.getAllByRole('button', { name: '新建信源' })[0])

  expect(screen.getByDisplayValue('B站 · mediacrawler')).toBeInTheDocument()
  expect(screen.getByLabelText('采集模式')).toHaveValue('search')
  expect(screen.getByText(/一个搜索信源对应一个稳定关键词/)).toBeInTheDocument()

  await userEvent.type(screen.getByLabelText('信源名称'), 'B站 AI Agent')
  await userEvent.type(screen.getByLabelText(/搜索关键词/), 'AI Agent')
  await userEvent.click(screen.getByRole('button', { name: '创建信源' }))

  await waitFor(() => expect(bodies).toHaveLength(1))
  expect(bodies[0]).toEqual(expect.objectContaining({
    connector_instance_id: 'instance-1',
    source_type: 'mediacrawler',
    mode: 'search',
    scope_key: 'search:AI Agent',
    external_ref: 'AI Agent',
  }))
})