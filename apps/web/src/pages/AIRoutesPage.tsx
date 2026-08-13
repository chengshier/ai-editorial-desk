import { useCallback, useEffect, useState } from 'react'
import type { AdminApi } from '../api'
import type { AiModel, AiRoute } from '../aiTypes'

type Props = { api: AdminApi }

type RouteDraft = {
  primary: string
  fallback: string
  timeout: string
  retry: string
  maxOutputTokens: string
  enabled: boolean
}

const generationPolicyFallbacks: Record<string, number> = {
  evidence_extraction: 4096,
  editorial_scoring: 4096,
  draft_generation: 6000,
}

function configuredMaxOutputTokens(route: AiRoute): string {
  const policy = route.config.generation_policy
  if (!policy || typeof policy !== 'object' || Array.isArray(policy)) return ''
  const value = (policy as Record<string, unknown>).max_output_tokens
  return typeof value === 'number' && Number.isInteger(value) && value > 0 ? String(value) : ''
}

function mergeMaxOutputTokens(config: Record<string, unknown>, value: string): Record<string, unknown> {
  const trimmed = value.trim()
  const existing = config.generation_policy
  const policy = existing && typeof existing === 'object' && !Array.isArray(existing)
    ? { ...(existing as Record<string, unknown>) }
    : {}

  if (!trimmed) {
    delete policy.max_output_tokens
  } else {
    const parsed = Number(trimmed)
    if (!Number.isInteger(parsed) || parsed <= 0) {
      throw new Error('最大输出 Token 必须是正整数，或留空使用代码默认值')
    }
    policy.max_output_tokens = parsed
  }

  const next = { ...config }
  if (Object.keys(policy).length > 0) next.generation_policy = policy
  else delete next.generation_policy
  return next
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
        maxOutputTokens: configuredMaxOutputTokens(route),
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
      const supportsGenerationPolicy = route.task_key in generationPolicyFallbacks
      const config = supportsGenerationPolicy
        ? mergeMaxOutputTokens(route.config, draft.maxOutputTokens)
        : route.config
      await api.request(`/api/v1/admin/ai/routes/${route.task_key}`, {
        method: 'PUT',
        body: JSON.stringify({
          primary_model_id: draft.primary || null,
          fallback_model_ids: draft.fallback.split(',').map(item => item.trim()).filter(Boolean),
          timeout_seconds: Number(draft.timeout),
          retry_limit: Number(draft.retry),
          budget_policy: route.budget_policy,
          config,
          enabled: draft.enabled,
        }),
      })
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '更新 AI Route 失败')
    }
  }

  return <section className="panel">
    <div className="panel-head"><div><h2>AI 路由</h2><small>为不同 AI 任务选择主模型、备用链和执行策略；每次保存创建新版本，仅影响新的调用。</small></div><button onClick={() => void load()}>刷新</button></div>
    {error && <div className="error-banner">{error}</div>}
    <div className="table-wrap"><table><thead><tr><th>任务类型</th><th>版本</th><th>主模型</th><th>备用模型链</th><th>最大输出 Token</th><th>超时（秒）</th><th>重试次数</th><th>已启用</th><th>操作</th></tr></thead><tbody>{routes.map(route => {
      const draft = drafts[route.task_key]
      if (!draft) return null
      const fallback = generationPolicyFallbacks[route.task_key]
      return <tr key={route.id}><td><strong>{route.task_key}</strong></td><td>v{route.version}</td><td><select value={draft.primary} onChange={e => updateDraft(route.task_key, { primary: e.target.value })}><option value="">未配置</option>{models.map(model => <option key={model.id} value={model.id}>{model.model_key} · {model.model_name}</option>)}</select></td><td><input style={{ minWidth: 260 }} value={draft.fallback} placeholder="模型 UUID，多个值用逗号分隔" onChange={e => updateDraft(route.task_key, { fallback: e.target.value })} /></td><td>{fallback ? <div><input aria-label={`${route.task_key} 最大输出 Token`} type="number" min={1} step={1} style={{ width: 110 }} value={draft.maxOutputTokens} placeholder={String(fallback)} onChange={e => updateDraft(route.task_key, { maxOutputTokens: e.target.value })} /><small style={{ display: 'block', whiteSpace: 'nowrap' }}>留空使用 {fallback}</small></div> : <span>—</span>}</td><td><input style={{ width: 70 }} value={draft.timeout} onChange={e => updateDraft(route.task_key, { timeout: e.target.value })} /></td><td><input style={{ width: 55 }} value={draft.retry} onChange={e => updateDraft(route.task_key, { retry: e.target.value })} /></td><td><input aria-label={`${route.task_key} 是否启用`} type="checkbox" checked={draft.enabled} onChange={e => updateDraft(route.task_key, { enabled: e.target.checked })} /></td><td><button className="primary" onClick={() => void save(route)}>保存为 v{route.version + 1}</button></td></tr>
    })}</tbody></table></div>
    <p className="notice">Evidence、Editorial Scoring 与 Draft 支持任务级最大输出 Token。数据库配置优先；留空时分别回退到代码默认值 4096 / 4096 / 6000。保存会创建新的 Route 版本，仅影响后续调用，并继续经过现有 AI Budget。</p>
  </section>
}
