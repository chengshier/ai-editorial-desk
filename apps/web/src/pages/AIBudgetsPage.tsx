import { useCallback, useEffect, useState } from 'react'
import type { AdminApi } from '../api'
import type { AiBudget } from '../aiTypes'

type Props = { api: AdminApi }

export function AIBudgetsPage({ api }: Props) {
  const [budgets, setBudgets] = useState<AiBudget[]>([])
  const [error, setError] = useState('')
  const [draft, setDraft] = useState({
    scope_type: 'global', scope_key: 'global', daily_cost_limit: '',
    monthly_cost_limit: '', daily_token_limit: '', unknown_usage_policy: 'block',
  })

  const load = useCallback(async () => {
    try {
      const page = await api.page<AiBudget>('/api/v1/admin/ai/budgets?page=1&page_size=100')
      setBudgets(page.items)
      setError('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '加载 AI Budget 失败')
    }
  }, [api])

  useEffect(() => { void load() }, [load])

  const create = async () => {
    try {
      await api.post('/api/v1/admin/ai/budgets', {
        scope_type: draft.scope_type,
        scope_key: draft.scope_key,
        enabled: true,
        daily_cost_limit: draft.daily_cost_limit || null,
        monthly_cost_limit: draft.monthly_cost_limit || null,
        daily_token_limit: draft.daily_token_limit ? Number(draft.daily_token_limit) : null,
        unknown_usage_policy: draft.unknown_usage_policy,
        config: {},
      })
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '创建 AI Budget 失败')
    }
  }

  const edit = async (budget: AiBudget) => {
    const dailyCost = window.prompt('Daily cost limit；留空表示不限制', budget.daily_cost_limit || '')
    if (dailyCost === null) return
    const monthlyCost = window.prompt('Monthly cost limit；留空表示不限制', budget.monthly_cost_limit || '')
    if (monthlyCost === null) return
    const dailyTokens = window.prompt('Daily token limit；留空表示不限制', budget.daily_token_limit?.toString() || '')
    if (dailyTokens === null) return
    try {
      await api.patch(`/api/v1/admin/ai/budgets/${budget.id}`, {
        daily_cost_limit: dailyCost || null,
        monthly_cost_limit: monthlyCost || null,
        daily_token_limit: dailyTokens ? Number(dailyTokens) : null,
      })
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '更新 AI Budget 失败')
    }
  }

  const toggle = async (budget: AiBudget) => {
    try {
      await api.patch(`/api/v1/admin/ai/budgets/${budget.id}`, { enabled: !budget.enabled })
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '更新 AI Budget 失败')
    }
  }

  return <section className="panel">
    <div className="panel-head"><div><h2>AI Budgets</h2><small>Global / Task / Provider scope；调用前 reserve，调用后 settle。</small></div><button onClick={() => void load()}>刷新</button></div>
    {error && <div className="error-banner">{error}</div>}
    <div className="form-grid">
      <label>Scope<select value={draft.scope_type} onChange={e => setDraft({ ...draft, scope_type: e.target.value, scope_key: e.target.value === 'global' ? 'global' : '' })}><option value="global">global</option><option value="task">task</option><option value="provider">provider</option></select></label>
      <label>Scope Key<input value={draft.scope_key} onChange={e => setDraft({ ...draft, scope_key: e.target.value })} /></label>
      <label>Unknown Usage<select value={draft.unknown_usage_policy} onChange={e => setDraft({ ...draft, unknown_usage_policy: e.target.value })}><option value="block">block</option><option value="allow_once">allow_once</option></select></label>
      <label>Daily Cost<input value={draft.daily_cost_limit} onChange={e => setDraft({ ...draft, daily_cost_limit: e.target.value })} /></label>
      <label>Monthly Cost<input value={draft.monthly_cost_limit} onChange={e => setDraft({ ...draft, monthly_cost_limit: e.target.value })} /></label>
      <label>Daily Tokens<input value={draft.daily_token_limit} onChange={e => setDraft({ ...draft, daily_token_limit: e.target.value })} /></label>
    </div>
    <div className="actions"><button onClick={() => void create()}>创建 Budget</button></div>
    <div className="table-wrap"><table><thead><tr><th>Scope</th><th>Daily Cost</th><th>Monthly Cost</th><th>Daily Tokens</th><th>Unknown Usage</th><th>状态</th><th>操作</th></tr></thead><tbody>{budgets.map(budget => <tr key={budget.id}><td>{budget.scope_type}:{budget.scope_key}</td><td>{budget.daily_cost_limit ?? '-'}</td><td>{budget.monthly_cost_limit ?? '-'}</td><td>{budget.daily_token_limit ?? '-'}</td><td>{budget.unknown_usage_policy}</td><td>{budget.enabled ? 'enabled' : 'disabled'}</td><td><div className="actions"><button onClick={() => void edit(budget)}>编辑</button><button onClick={() => void toggle(budget)}>{budget.enabled ? '停用' : '启用'}</button></div></td></tr>)}</tbody></table></div>
    <p className="notice">未知 usage/cost 不会被当作 0。默认策略 block；allow_once 也只允许受并发保护的一次未知用量。</p>
  </section>
}
