import { useCallback, useEffect, useState } from 'react'
import type { AdminApi } from '../api'
import type { AiModel, AiRoute } from '../aiTypes'

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
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const [routePage, modelPage] = await Promise.all([
        api.page<AiRoute>('/api/v1/admin/ai/routes?page=1&page_size=100'),
        api.page<AiModel>('/api/v1/admin/ai/models?page=1&page_size=100'),
      ])
      setRoutes(routePage.items)
      setModels(modelPage.items)
      setDrafts(Object.fromEntries(routePage.items.map(route => [route.task_key, {
        primary: route.primary_model_id || '',
        fallback: route.fallback_model_ids.join(','),
        timeout: String(route.timeout_seconds),
        retry: String(route.retry_limit),
        enabled: route.enabled,
      }])))
      setError('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '加载 AI Route 失败')
    }
  }, [api])

  useEffect(() => { void load() }, [load])

  const updateDraft = (task: string, patch: Partial<RouteDraft>) => {
    setDrafts(current => ({ ...current, [task]: { ...current[task], ...patch } }))
  }

  const save = async (route: AiRoute) => {
    const draft = drafts[route.task_key]
    if (!draft) return
    try {
      await api.request(`/api/v1/admin/ai/routes/${route.task_key}`, {
        method: 'PUT',
        body: JSON.stringify({
          primary_model_id: draft.primary || null,
          fallback_model_ids: draft.fallback.split(',').map(item => item.trim()).filter(Boolean),
          timeout_seconds: Number(draft.timeout),
          retry_limit: Number(draft.retry),
          budget_policy: route.budget_policy,
          config: route.config,
          enabled: draft.enabled,
        }),
      })
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '更新 AI Route 失败')
    }
  }

  return <section className="panel">
    <div className="panel-head"><div><h2>AI Routes</h2><small>每次保存创建新版本，仅影响新 Invocation。</small></div><button onClick={() => void load()}>刷新</button></div>
    {error && <div className="error-banner">{error}</div>}
    <div className="table-wrap"><table><thead><tr><th>Task</th><th>Version</th><th>Primary Model</th><th>Fallback Chain</th><th>Timeout</th><th>Retry</th><th>Enabled</th><th>操作</th></tr></thead><tbody>{routes.map(route => {
      const draft = drafts[route.task_key]
      if (!draft) return null
      return <tr key={route.id}><td><strong>{route.task_key}</strong></td><td>v{route.version}</td><td><select value={draft.primary} onChange={e => updateDraft(route.task_key, { primary: e.target.value })}><option value="">未配置</option>{models.map(model => <option key={model.id} value={model.id}>{model.model_key} · {model.model_name}</option>)}</select></td><td><input style={{ minWidth: 260 }} value={draft.fallback} placeholder="model UUID, model UUID" onChange={e => updateDraft(route.task_key, { fallback: e.target.value })} /></td><td><input style={{ width: 70 }} value={draft.timeout} onChange={e => updateDraft(route.task_key, { timeout: e.target.value })} /></td><td><input style={{ width: 55 }} value={draft.retry} onChange={e => updateDraft(route.task_key, { retry: e.target.value })} /></td><td><input type="checkbox" checked={draft.enabled} onChange={e => updateDraft(route.task_key, { enabled: e.target.checked })} /></td><td><button onClick={() => void save(route)}>保存为 v{route.version + 1}</button></td></tr>
    })}</tbody></table></div>
    <p className="notice">M4-A 仅建立 route 能力；Evidence、Editorial、Draft 任务目前不会被业务层消费。</p>
  </section>
}
