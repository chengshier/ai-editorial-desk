import { afterEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AdminApi } from '../api'
import { AIBudgetsPage } from './AIBudgetsPage'

afterEach(() => vi.unstubAllGlobals())

it('shows the shared empty state when no AI budget exists', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ items: [], page: 1, page_size: 100, total: 0, has_next: false })))
  render(<AIBudgetsPage api={new AdminApi({ apiBaseUrl: 'http://api', adminToken: 'token', actorId: 'editor' })}/>)
  expect(await screen.findByText('暂无 AI 预算')).toBeInTheDocument()
  expect(screen.getByText('创建预算后，会在这里显示成本与 Token 约束。')).toBeInTheDocument()
})

it('does not describe a failed request as an empty budget list', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: '管理员凭据无效' }), { status: 401, headers: { 'Content-Type': 'application/json' } })))
  render(<AIBudgetsPage api={new AdminApi({ apiBaseUrl: 'http://api', adminToken: 'token', actorId: 'editor' })}/>)
  expect(await screen.findByText('管理员凭据无效')).toBeInTheDocument()
  expect(screen.queryByText('暂无 AI 预算')).not.toBeInTheDocument()
})
