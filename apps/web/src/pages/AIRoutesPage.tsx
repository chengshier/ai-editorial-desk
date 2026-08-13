import { useCallback, useEffect, useMemo, useState } from 'react'
import type { AdminApi } from '../api'
import type { AiModel, AiRoute } from '../aiTypes'
import { Drawer, Empty, ErrorBanner, ResourceHeader } from '../components/common'

type Props = { api: AdminApi }

type RouteDraft = {
  primary: string
  fallback: string
  timeout: string
  retry: string
  enabled: boolean
}

export function AIRoutesPage({ api }: Props) {
  const [routes, setRoutes] = useState<AiRoute[]>([])
  const [models, setModels] = useState<AiModel[]>([])
  const [drafts, setDrafts] = useState<Record<string, RouteDraft>>({})
  const [editingTask, setEditingTask] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const [routePage, modelPage] = await Promise.all([
        api.page<AiRoute>('/api/v1/admin/ai/routes?page=1&page_size=100'),
        api.page<AiModel>('/api/v1/admin/ai/models?page=1&page_size=100'),
      ])
      setRoutes(routePage.items)
      setModels(modelPage.items)
      setDrafts(Object.fromEntries(routePage.items.map((route) => [route.task_key, {
        primary: route.primary_model_id || '',
        fallback: route.fallback_model_ids.join(','),
        timeout: String(route.timeout_seconds),
        retry: String(route.retry_limit),
        enabled: route.enabled,
      }])))
      setError('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '加载 AI 路由失败')
    }
  }, [api])

  useEffect(() => { void load() }, [load])

  const updateDraft = (task: string, patch: Partial<RouteDraft>) => {
    setDrafts((current) => ({ ...current, [task]: { ...current[task], ...patch } }))
  }

  const selectedRoute = useMemo(() => routes.find((route) => route.task_key === editingTask) || null, [routes, editingTask])
  const selectedDraft = selectedRoute ? drafts[selectedRoute.task_key] : undefined
  const modelLabel = (id: string | null | undefined) => {
    if (!id) return '未配置'
    const model = models.find((item) => item.id === id)
    return model ? `${model.model_key} · ${model.model_name}` : id
  }

  const save = async (route: AiRoute) => {
    const draft = drafts[route.task_key]
    if (!draft) return
    if (draft.timeout.trim()==='' || Number(draft.timeout)<=0) return setError('超时时间必须大于 0')
    if (draft.retry.trim()==='' || Number(draft.retry)<0) return setError('重试次数不能小于 0')
    setPendingAction(true)
    setError('')
    try {
      await api.request(`/api/v1/admin/ai/routes/${route.task_key}`, {
        method: 'PUT',
        body: JSON.stringify({
          primary_model_id: draft.primary || null,
          fallback_model_ids: draft.fallback.split(',').map((item) => item.trim()).filter(Boolean),
          timeout_seconds: Number(draft.timeout),
          retry_limit: Number(draft.retry),
          budget_policy: route.budget_policy,
          config: route.config,
          enabled: draft.enabled,
        }),
      })
      setMessage(`${route.task_key} 已保存为新路由版本。`)
      await load()
      setEditingTask(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '更新 AI 路由失败')
    } finally {
      setPendingAction(false)
    }
  }

  return <div className="operations-page">
    <ErrorBanner error={error || null}/>
    {message&&<div className="success-banner">{message}</div>}
    <section className="panel">
      <ResourceHeader title="AI 路由" description="路由决定不同 AI 任务使用哪个主模型、备用链和执行策略。列表展示当前版本，配置修改通过独立流程保存为新版本。" actions={<button onClick={() => void load()}>刷新</button>}/>
      {routes.length===0 ? <Empty text="暂无 AI 路由" helper="当前没有可配置的任务路由；路由任务由系统能力注册。"/> : <div className="table-wrap"><table><thead><tr><th>任务类型</th><th>版本</th><th>主模型</th><th>备用模型</th><th>执行策略</th><th>状态</th><th>操作</th></tr></thead><tbody>{routes.map((route) => <tr key={route.id}>
        <td><strong>{route.task_key}</strong></td>
        <td>v{route.version}</td>
        <td>{modelLabel(route.primary_model_id)}</td>
        <td>{route.fallback_model_ids.length ? `${route.fallback_model_ids.length} 个备用模型` : '未配置'}</td>
        <td>{route.timeout_seconds} 秒超时 · {route.retry_limit} 次重试</td>
        <td>{route.enabled?'已启用':'已停用'}</td>
        <td><button className="primary" onClick={() => { setEditingTask(route.task_key); setError('') }}>配置路由</button></td>
      </tr>)}</tbody></table></div>}
      <p className="notice">每次保存都会创建新版本，只影响新的 AI 调用；尚未接入业务消费的任务保持配置态，不会自动触发 AI。</p>
    </section>

    <Drawer
      open={Boolean(selectedRoute&&selectedDraft)}
      title={selectedRoute?`配置路由 · ${selectedRoute.task_key}`:'配置 AI 路由'}
      description={selectedRoute?`当前 v${selectedRoute.version}，保存后将创建 v${selectedRoute.version+1}。`:undefined}
      onClose={() => setEditingTask(null)}
      footer={<><button disabled={pendingAction} onClick={() => setEditingTask(null)}>取消</button><button className="primary" disabled={pendingAction||!selectedRoute} onClick={() => selectedRoute&&void save(selectedRoute)}>{pendingAction?'正在保存…':selectedRoute?`保存为 v${selectedRoute.version+1}`:'保存'}</button></>}
    >
      {selectedRoute&&selectedDraft&&<>
        <div className="drawer-section"><h3>模型选择</h3><p>主模型优先执行；备用链按后端现有路由语义依次使用。模型 ID 仍保持内部稳定标识。</p><div className="form-grid"><label className="field-full">主模型<select value={selectedDraft.primary} onChange={(event) => updateDraft(selectedRoute.task_key, { primary: event.target.value })}><option value="">未配置</option>{models.map((model) => <option key={model.id} value={model.id}>{model.model_key} · {model.model_name}</option>)}</select></label><label className="field-full">备用模型 ID<input value={selectedDraft.fallback} placeholder="多个模型 UUID 用逗号分隔" onChange={(event) => updateDraft(selectedRoute.task_key, { fallback: event.target.value })}/><small>当前后端路由契约使用模型 UUID；此处不改变既有 API 语义。</small></label></div></div>
        <div className="drawer-section"><h3>执行策略</h3><p>这些设置仅影响新的调用，不会修改已有 Invocation。</p><div className="form-grid"><label>超时时间（秒）<input type="number" min="1" value={selectedDraft.timeout} onChange={(event) => updateDraft(selectedRoute.task_key, { timeout: event.target.value })}/></label><label>重试次数<input type="number" min="0" value={selectedDraft.retry} onChange={(event) => updateDraft(selectedRoute.task_key, { retry: event.target.value })}/></label><label className="toggle-row field-full"><span><strong>启用该路由</strong><small>关闭后新的业务调用不会使用该任务路由。</small></span><input type="checkbox" checked={selectedDraft.enabled} onChange={(event) => updateDraft(selectedRoute.task_key, { enabled: event.target.checked })}/></label></div></div>
      </>}
    </Drawer>
  </div>
}
