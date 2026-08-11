import { useCallback, useEffect, useState } from 'react'
import type { AdminApi } from '../api'
import type { AiModel, AiProvider } from '../aiTypes'
import { enabledLabel, providerTypeLabel, validationStatusLabel } from '../uiLabels'

type Props = { api: AdminApi }

export function AIProvidersPage({ api }: Props) {
  const [providers, setProviders] = useState<AiProvider[]>([])
  const [models, setModels] = useState<AiModel[]>([])
  const [error, setError] = useState('')
  const [providerDraft, setProviderDraft] = useState({
    provider_key: '', display_name: '', provider_type: 'openai_compatible',
    base_url: '', credential_ref: '',
  })
  const [modelDraft, setModelDraft] = useState({
    provider_id: '', model_key: '', model_name: '', capabilities: 'text_generation',
    pricing_version: 'unpriced-v1', dimensions: '', structured_output_mode: 'json_schema',
  })

  const load = useCallback(async () => {
    try {
      const [providerPage, modelPage] = await Promise.all([
        api.page<AiProvider>('/api/v1/admin/ai/providers?page=1&page_size=100'),
        api.page<AiModel>('/api/v1/admin/ai/models?page=1&page_size=100'),
      ])
      setProviders(providerPage.items)
      setModels(modelPage.items)
      setError('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '加载 AI Provider 失败')
    }
  }, [api])

  useEffect(() => { void load() }, [load])

  const createProvider = async () => {
    try {
      await api.post('/api/v1/admin/ai/providers', {
        ...providerDraft,
        credential_ref: providerDraft.credential_ref || null,
        enabled: false,
        timeout_seconds: 30,
        max_concurrency: 4,
        retry_limit: 1,
        config: {},
      })
      setProviderDraft({ ...providerDraft, provider_key: '', display_name: '', base_url: '', credential_ref: '' })
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '创建 Provider 失败')
    }
  }

  const createModel = async () => {
    try {
      await api.post('/api/v1/admin/ai/models', {
        provider_id: modelDraft.provider_id,
        model_key: modelDraft.model_key,
        model_name: modelDraft.model_name,
        capabilities: modelDraft.capabilities.split(',').map(item => item.trim()).filter(Boolean),
        enabled: false,
        pricing_version: modelDraft.pricing_version,
        dimensions: modelDraft.dimensions ? Number(modelDraft.dimensions) : null,
        config: { structured_output_mode: modelDraft.structured_output_mode },
      })
      setModelDraft({ ...modelDraft, model_key: '', model_name: '', dimensions: '' })
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '创建 Model 失败')
    }
  }

  const toggleProvider = async (provider: AiProvider) => {
    await api.post(`/api/v1/admin/ai/providers/${provider.id}/${provider.enabled ? 'disable' : 'enable'}`)
    await load()
  }

  const replaceCredential = async (provider: AiProvider) => {
    const next = window.prompt('输入新的 opaque credential_ref，例如 env://AI_PROVIDER_KEY。不会显示旧值。')
    if (next === null) return
    await api.patch(`/api/v1/admin/ai/providers/${provider.id}`, { replace_credential_ref: next || null })
    await load()
  }

  const toggleModel = async (model: AiModel) => {
    await api.post(`/api/v1/admin/ai/models/${model.id}/${model.enabled ? 'disable' : 'enable'}`)
    await load()
  }

  const testModel = async (model: AiModel) => {
    const response = await api.post<{ status: string; error_code: string | null }>(
      `/api/v1/admin/ai/providers/${model.provider_id}/test`, { model_id: model.id },
    )
    window.alert(response.error_code ? `${response.status}: ${response.error_code}` : response.status)
    await load()
  }

  return <>
    <section className="panel">
      <div className="panel-head"><div><h2>AI 服务商</h2><small>配置模型服务连接、凭据引用与可用状态。</small></div><button onClick={() => void load()}>刷新</button></div>
      {error && <div className="error-banner">{error}</div>}
      <div className="form-grid">
        <label>服务商标识<input value={providerDraft.provider_key} onChange={e => setProviderDraft({ ...providerDraft, provider_key: e.target.value })} /></label>
        <label>服务商名称<input value={providerDraft.display_name} onChange={e => setProviderDraft({ ...providerDraft, display_name: e.target.value })} /></label>
        <label>服务类型<select value={providerDraft.provider_type} onChange={e => setProviderDraft({ ...providerDraft, provider_type: e.target.value })}><option value="openai_compatible">OpenAI 兼容服务</option><option value="local_openai_compatible">本地 OpenAI 兼容服务</option></select></label>
        <label>服务地址（Base URL）<input value={providerDraft.base_url} onChange={e => setProviderDraft({ ...providerDraft, base_url: e.target.value })} /></label>
        <label>凭据引用<input type="password" autoComplete="off" placeholder="例如 env://AI_PROVIDER_KEY" value={providerDraft.credential_ref} onChange={e => setProviderDraft({ ...providerDraft, credential_ref: e.target.value })} /></label>
      </div>
      <div className="actions"><button className="primary" onClick={() => void createProvider()}>创建服务商</button></div>
      <div className="table-wrap"><table><thead><tr><th>服务商</th><th>类型</th><th>状态</th><th>凭据</th><th>验证状态</th><th>模型数</th><th>最近调用 / 错误率</th><th>操作</th></tr></thead><tbody>{providers.map(provider => <tr key={provider.id}><td><strong>{provider.display_name}</strong><br /><small>{provider.provider_key}</small></td><td>{providerTypeLabel[provider.provider_type]||provider.provider_type}</td><td>{enabledLabel(provider.enabled)}</td><td>{provider.credential_configured ? '已配置' : '未配置'}<br /><small>{provider.credential_ref_masked || '—'}</small></td><td>{validationStatusLabel[provider.validation_status]}</td><td>{provider.model_count}</td><td>{provider.last_invocation_at || '暂无'}<br /><small>{provider.error_rate === null ? '暂无' : `${(provider.error_rate * 100).toFixed(1)}%`}</small></td><td><div className="actions"><button onClick={() => void toggleProvider(provider)}>{provider.enabled ? '停用' : '启用'}</button><button onClick={() => void replaceCredential(provider)}>更换凭据</button></div></td></tr>)}</tbody></table></div>
    </section>
    <section className="panel">
      <div className="panel-head"><div><h2>AI 模型</h2><small>登记服务商提供的模型与结构化输出能力。</small></div></div>
      <div className="form-grid">
        <label>所属服务商<select value={modelDraft.provider_id} onChange={e => setModelDraft({ ...modelDraft, provider_id: e.target.value })}><option value="">请选择</option>{providers.map(provider => <option key={provider.id} value={provider.id}>{provider.provider_key}</option>)}</select></label>
        <label>模型标识<input value={modelDraft.model_key} onChange={e => setModelDraft({ ...modelDraft, model_key: e.target.value })} /></label>
        <label>服务商模型名称<input value={modelDraft.model_name} onChange={e => setModelDraft({ ...modelDraft, model_name: e.target.value })} /></label>
        <label>模型能力<input placeholder="如 text_generation,structured_output" value={modelDraft.capabilities} onChange={e => setModelDraft({ ...modelDraft, capabilities: e.target.value })} /></label>
        <label>结构化输出方式<select value={modelDraft.structured_output_mode} onChange={e => setModelDraft({ ...modelDraft, structured_output_mode: e.target.value })}><option value="json_schema">JSON Schema</option><option value="json_object">JSON Object</option></select></label>
        <label>计价版本<input value={modelDraft.pricing_version} onChange={e => setModelDraft({ ...modelDraft, pricing_version: e.target.value })} /></label>
        <label>向量维度<input value={modelDraft.dimensions} onChange={e => setModelDraft({ ...modelDraft, dimensions: e.target.value })} /></label>
      </div>
      <div className="actions"><button className="primary" onClick={() => void createModel()}>创建模型</button></div>
      <div className="table-wrap"><table><thead><tr><th>模型标识</th><th>模型名称</th><th>能力</th><th>计价版本</th><th>向量维度</th><th>状态</th><th>操作</th></tr></thead><tbody>{models.map(model => <tr key={model.id}><td>{model.model_key}</td><td>{model.model_name}</td><td>{model.capabilities.join(', ')}</td><td>{model.pricing_version}</td><td>{model.dimensions ?? '—'}</td><td>{enabledLabel(model.enabled)}</td><td><div className="actions"><button onClick={() => void toggleModel(model)}>{model.enabled ? '停用' : '启用'}</button><button onClick={() => void testModel(model)}>连接测试</button></div></td></tr>)}</tbody></table></div>
    </section>
  </>
}
