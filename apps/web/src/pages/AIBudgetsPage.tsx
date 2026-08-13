import { useCallback, useEffect, useState } from 'react'
import type { AdminApi } from '../api'
import type { AiBudget } from '../aiTypes'
import { Drawer, Empty, ErrorBanner, ResourceHeader } from '../components/common'
import { enabledLabel, numberLabel, policyLabel, scopeLabel } from '../uiLabels'

type Props = { api: AdminApi }

type BudgetDraft = {
  scope_type: string
  scope_key: string
  daily_cost_limit: string
  monthly_cost_limit: string
  daily_token_limit: string
  unknown_usage_policy: string
}

const initialDraft: BudgetDraft = {
  scope_type: 'global',
  scope_key: 'global',
  daily_cost_limit: '',
  monthly_cost_limit: '',
  daily_token_limit: '',
  unknown_usage_policy: 'block',
}

export function AIBudgetsPage({ api }: Props) {
  const [budgets, setBudgets] = useState<AiBudget[]>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [pendingAction, setPendingAction] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editing, setEditing] = useState<AiBudget | null>(null)
  const [draft, setDraft] = useState<BudgetDraft>(initialDraft)

  const load = useCallback(async () => {
    try {
      const page = await api.page<AiBudget>('/api/v1/admin/ai/budgets?page=1&page_size=100')
      setBudgets(page.items)
      setError('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '加载 AI 预算失败')
    }
  }, [api])

  useEffect(() => { void load() }, [load])

  const openCreate = () => {
    setEditing(null)
    setDraft(initialDraft)
    setError('')
    setDrawerOpen(true)
  }

  const openEdit = (budget: AiBudget) => {
    setEditing(budget)
    setDraft({
      scope_type: budget.scope_type,
      scope_key: budget.scope_key,
      daily_cost_limit: budget.daily_cost_limit || '',
      monthly_cost_limit: budget.monthly_cost_limit || '',
      daily_token_limit: budget.daily_token_limit?.toString() || '',
      unknown_usage_policy: budget.unknown_usage_policy,
    })
    setError('')
    setDrawerOpen(true)
  }

  const save = async () => {
    if (!draft.scope_key.trim()) return setError('请填写范围标识')
    setPendingAction('save')
    setError('')
    try {
      if (editing) {
        await api.patch(`/api/v1/admin/ai/budgets/${editing.id}`, {
          daily_cost_limit: draft.daily_cost_limit || null,
          monthly_cost_limit: draft.monthly_cost_limit || null,
          daily_token_limit: draft.daily_token_limit ? Number(draft.daily_token_limit) : null,
        })
        setMessage('AI 预算已更新。')
      } else {
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
        setMessage('AI 预算已创建。')
      }
      await load()
      setDrawerOpen(false)
      setEditing(null)
      setDraft(initialDraft)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : editing ? '更新 AI 预算失败' : '创建 AI 预算失败')
    } finally {
      setPendingAction(null)
    }
  }

  const toggle = async (budget: AiBudget) => {
    setPendingAction(`toggle:${budget.id}`)
    setError('')
    try {
      await api.patch(`/api/v1/admin/ai/budgets/${budget.id}`, { enabled: !budget.enabled })
      setMessage(budget.enabled ? 'AI 预算已停用。' : 'AI 预算已启用。')
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '更新 AI 预算失败')
    } finally {
      setPendingAction(null)
    }
  }

  return <div className="operations-page">
    <ErrorBanner error={error || null}/>
    {message&&<div className="success-banner">{message}</div>}
    <section className="panel">
      <ResourceHeader
        title="AI 预算"
        description="为全局、任务或服务商设置调用成本与 Token 上限。日常先查看预算状态，需要新增或调整时再进入配置。"
        actions={<><button onClick={() => void load()}>刷新</button><button className="primary" onClick={openCreate}>创建预算</button></>}
      />
      {!error && (budgets.length===0 ? <Empty text="暂无 AI 预算" helper="创建预算后，会在这里显示成本与 Token 约束。" action={<button className="primary" onClick={openCreate}>创建预算</button>}/> : <div className="table-wrap"><table><thead><tr><th>预算范围</th><th>每日成本</th><th>每月成本</th><th>每日 Token</th><th>未知用量策略</th><th>状态</th><th>操作</th></tr></thead><tbody>{budgets.map((budget) => <tr key={budget.id}>
        <td><strong>{scopeLabel[budget.scope_type]||budget.scope_type}</strong><small className="technical-meta">{budget.scope_key}</small></td>
        <td>{numberLabel(budget.daily_cost_limit)}</td>
        <td>{numberLabel(budget.monthly_cost_limit)}</td>
        <td>{budget.daily_token_limit ?? '—'}</td>
        <td>{policyLabel[budget.unknown_usage_policy]||budget.unknown_usage_policy}</td>
        <td>{enabledLabel(budget.enabled)}</td>
        <td><div className="actions action-cell"><button className="primary" disabled={Boolean(pendingAction)} onClick={() => openEdit(budget)}>调整预算</button><button disabled={Boolean(pendingAction)} onClick={() => void toggle(budget)}>{pendingAction===`toggle:${budget.id}`?'正在处理…':budget.enabled?'停用':'启用'}</button></div></td>
      </tr>)}</tbody></table></div>)}
      <p className="notice">未知用量或成本不会被当作 0。默认策略为“阻止调用”；“允许一次”也只允许受并发保护的一次未知用量。</p>
    </section>

    <Drawer
      open={drawerOpen}
      title={editing?'调整 AI 预算':'创建 AI 预算'}
      description={editing?'当前版本只允许调整成本和 Token 上限；预算范围与未知用量策略保持创建时语义。':'先确定预算适用范围，再设置成本、Token 与未知用量策略。'}
      onClose={() => { setDrawerOpen(false); setEditing(null); setDraft(initialDraft) }}
      footer={<><button disabled={pendingAction==='save'} onClick={() => { setDrawerOpen(false); setEditing(null); setDraft(initialDraft) }}>取消</button><button className="primary" disabled={pendingAction==='save'} onClick={() => void save()}>{pendingAction==='save'?'正在保存…':editing?'保存预算':'创建预算'}</button></>}
    >
      <div className="drawer-section"><h3>适用范围</h3><p>全局预算覆盖所有未被更具体预算覆盖的调用；任务或服务商预算使用稳定范围标识。</p><div className="form-grid"><label>预算范围<select disabled={Boolean(editing)} value={draft.scope_type} onChange={(event) => setDraft({ ...draft, scope_type: event.target.value, scope_key: event.target.value === 'global' ? 'global' : '' })}><option value="global">全局</option><option value="task">任务</option><option value="provider">服务商</option></select></label><label>范围标识<input disabled={Boolean(editing)} value={draft.scope_key} onChange={(event) => setDraft({ ...draft, scope_key: event.target.value })}/></label><label className="field-full">未知用量处理策略<select disabled={Boolean(editing)} value={draft.unknown_usage_policy} onChange={(event) => setDraft({ ...draft, unknown_usage_policy: event.target.value })}><option value="block">阻止调用</option><option value="allow_once">允许一次</option></select></label></div></div>
      <div className="drawer-section"><h3>成本与 Token 限制</h3><p>留空表示该项不单独限制；实际结算与预算判断仍以后端记录为准。</p><div className="form-grid"><label>每日成本上限<input inputMode="decimal" value={draft.daily_cost_limit} onChange={(event) => setDraft({ ...draft, daily_cost_limit: event.target.value })}/></label><label>每月成本上限<input inputMode="decimal" value={draft.monthly_cost_limit} onChange={(event) => setDraft({ ...draft, monthly_cost_limit: event.target.value })}/></label><label>每日 Token 上限<input type="number" min="0" value={draft.daily_token_limit} onChange={(event) => setDraft({ ...draft, daily_token_limit: event.target.value })}/></label></div></div>
    </Drawer>
  </div>
}
