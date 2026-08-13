import { useCallback, useEffect, useState } from 'react'
import type { AdminApi } from '../api'
import type { AiModel, AiProvider } from '../aiTypes'
import { Drawer, Empty, ErrorBanner, ResourceHeader } from '../components/common'
import { enabledLabel, providerTypeLabel, validationStatusLabel } from '../uiLabels'

type Props = { api: AdminApi }
type DrawerMode = 'provider' | 'provider-edit' | 'model' | 'model-edit' | 'credential' | null

type ModelDraft = {
  provider_id: string
  model_key: string
  model_name: string
  capabilities: string
  pricing_version: string
  dimensions: string
  structured_output_mode: 'json_schema' | 'json_object'
}

type ModelEditDraft = Omit<ModelDraft, 'provider_id' | 'model_key'>

const emptyProviderDraft = {
  provider_key: '', display_name: '', provider_type: 'openai_compatible',
  base_url: '', credential_ref: '',
}
const emptyProviderEditDraft = { display_name: '', base_url: '' }
const emptyModelDraft: ModelDraft = {
  provider_id: '', model_key: '', model_name: '', capabilities: 'text_generation',
  pricing_version: 'unpriced-v1', dimensions: '', structured_output_mode: 'json_object',
}
const emptyModelEditDraft: ModelEditDraft = {
  model_name: '', capabilities: '', pricing_version: '', dimensions: '', structured_output_mode: 'json_object',
}

function credentialState(provider: AiProvider): { title: string; detail: string } {
  if (provider.credential_configured) return { title: '凭据可用', detail: '后端已从进程环境或受控 .env 解析到真实凭据，可进行连接测试。' }
  if (provider.credential_ref_masked) return { title: '引用已保存', detail: '已保存 env:// 引用，但当前后端未解析到对应真实凭据。' }
  return { title: '未配置引用', detail: '先保存 env://VARIABLE_NAME，再通过进程环境或项目 .env 提供真实 Secret。' }
}

function structuredOutputMode(model: AiModel): 'json_schema' | 'json_object' {
  return model.config.structured_output_mode === 'json_object' ? 'json_object' : 'json_schema'
}

function structuredOutputModeLabel(model: AiModel): string {
  if (!model.capabilities.includes('structured_output')) return '—'
  return structuredOutputMode(model) === 'json_object' ? 'JSON Object' : 'JSON Schema'
}

function connectionFailureMessage(provider: AiProvider | undefined, model: AiModel, errorCode: string | null): string {
  const code = errorCode || 'UNKNOWN_PROVIDER_ERROR'
  if (code === 'CREDENTIAL_NOT_CONFIGURED') return '连接测试失败：后端没有解析到该服务商的真实凭据。请检查 env:// 引用与 .env / 云端 Secret 的变量名是否一致。'
  if (code === 'AUTH_ERROR') return '连接测试失败：服务商认证失败。请确认 API Key 有效、未过期，并且当前凭据属于这个服务商。'
  if (code === 'MODEL_NOT_FOUND') return '连接测试失败：服务商未找到当前模型或接口端点。请检查模型名称与 Base URL。'
  if (code === 'RATE_LIMITED') return '连接测试失败：服务商触发限流。请稍后重试，并检查账号并发与配额。'
  if (code === 'TIMEOUT') return '连接测试失败：服务商请求超时。请检查网络、服务地址和 Provider 可用性。'
  if (code === 'NETWORK_ERROR') return '连接测试失败：后端无法正常访问服务商。请检查 DNS、网络和 Base URL。'
  if (code === 'PROVIDER_UNAVAILABLE') return '连接测试失败：服务商暂时不可用或返回 5xx。请稍后重试。'
  if (code === 'INVALID_RESPONSE') return '连接测试失败：服务商返回了系统无法解析的响应。请检查兼容接口和模型能力。'
  if (code === 'STRUCTURED_OUTPUT_INVALID') return '连接测试失败：服务商已响应，但返回内容不符合要求的结构化输出格式。请检查模型的结构化输出方式。'
  if (code === 'INVALID_REQUEST') {
    const providerName = `${provider?.provider_key || ''} ${provider?.display_name || ''}`.toLowerCase()
    const mode = structuredOutputMode(model)
    if (providerName.includes('deepseek') && model.capabilities.includes('structured_output') && mode === 'json_schema') {
      return '连接测试失败：服务商拒绝了请求（INVALID_REQUEST）。当前模型配置为 JSON Schema；DeepSeek 的 JSON Output 使用 JSON Object，请点击“编辑模型”把结构化输出方式改为 JSON Object 后重试。'
    }
    return '连接测试失败：服务商拒绝了请求（INVALID_REQUEST）。常见原因是模型名称、Base URL、请求能力或结构化输出方式与厂商接口不匹配。'
  }
  return `连接测试失败：${code}。可到“AI 调用记录”查看本次 provider_connection_test 的详细尝试信息。`
}

export function AIProvidersPage({ api }: Props) {
  const [providers, setProviders] = useState<AiProvider[]>([])
  const [models, setModels] = useState<AiModel[]>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [pendingAction, setPendingAction] = useState<string | null>(null)
  const [drawerMode, setDrawerMode] = useState<DrawerMode>(null)
  const [credentialProvider, setCredentialProvider] = useState<AiProvider | null>(null)
  const [credentialDraft, setCredentialDraft] = useState('')
  const [editingProvider, setEditingProvider] = useState<AiProvider | null>(null)
  const [providerEditDraft, setProviderEditDraft] = useState(emptyProviderEditDraft)
  const [providerDraft, setProviderDraft] = useState(emptyProviderDraft)
  const [modelDraft, setModelDraft] = useState<ModelDraft>(emptyModelDraft)
  const [editingModel, setEditingModel] = useState<AiModel | null>(null)
  const [modelEditDraft, setModelEditDraft] = useState<ModelEditDraft>(emptyModelEditDraft)

  const load = useCallback(async () => {
    try {
      const [providerPage, modelPage] = await Promise.all([
        api.page<AiProvider>('/api/v1/admin/ai/providers?page=1&page_size=100'),
        api.page<AiModel>('/api/v1/admin/ai/models?page=1&page_size=100'),
      ])
      setProviders(providerPage.items)
      setModels(modelPage.items)
      setModelDraft((current) => current.provider_id || !providerPage.items[0] ? current : { ...current, provider_id: providerPage.items[0].id })
      setError('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '加载 AI 服务商失败')
    }
  }, [api])

  useEffect(() => { void load() }, [load])

  const openProvider = () => {
    setProviderDraft(emptyProviderDraft)
    setError('')
    setMessage('')
    setDrawerMode('provider')
  }

  const openProviderEdit = (provider: AiProvider) => {
    setEditingProvider(provider)
    setProviderEditDraft({ display_name: provider.display_name, base_url: provider.base_url })
    setError('')
    setMessage('')
    setDrawerMode('provider-edit')
  }

  const openModel = () => {
    setModelDraft({ ...emptyModelDraft, provider_id: providers[0]?.id || '' })
    setError('')
    setMessage('')
    setDrawerMode('model')
  }

  const openModelEdit = (model: AiModel) => {
    setEditingModel(model)
    setModelEditDraft({
      model_name: model.model_name,
      capabilities: model.capabilities.join(','),
      pricing_version: model.pricing_version,
      dimensions: model.dimensions === null ? '' : String(model.dimensions),
      structured_output_mode: structuredOutputMode(model),
    })
    setError('')
    setMessage('')
    setDrawerMode('model-edit')
  }

  const createProvider = async () => {
    if (!providerDraft.provider_key.trim() || !providerDraft.display_name.trim() || !providerDraft.base_url.trim()) return setError('请填写服务商标识、名称和服务地址')
    setPendingAction('create-provider')
    setError('')
    try {
      const created = await api.post<AiProvider>('/api/v1/admin/ai/providers', {
        ...providerDraft,
        credential_ref: providerDraft.credential_ref.trim() || null,
        enabled: false,
        timeout_seconds: 30,
        max_concurrency: 4,
        retry_limit: 1,
        config: {},
      })
      setMessage(created.credential_configured ? 'AI 服务商已创建，凭据可用；服务商默认保持停用。' : created.credential_ref_masked ? 'AI 服务商已创建，凭据引用已保存，但后端尚未解析到真实凭据。' : 'AI 服务商已创建，尚未配置凭据引用；服务商默认保持停用。')
      setProviderDraft(emptyProviderDraft)
      await load()
      setDrawerMode(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '创建 AI 服务商失败')
    } finally {
      setPendingAction(null)
    }
  }

  const updateProvider = async () => {
    if (!editingProvider) return
    if (!providerEditDraft.display_name.trim() || !providerEditDraft.base_url.trim()) return setError('服务商名称和服务地址不能为空')
    setPendingAction('update-provider')
    setError('')
    try {
      await api.patch<AiProvider>(`/api/v1/admin/ai/providers/${editingProvider.id}`, {
        display_name: providerEditDraft.display_name.trim(),
        base_url: providerEditDraft.base_url.trim(),
      })
      setMessage('AI 服务商连接信息已更新。后续连接测试与业务调用将使用新的 Base URL。')
      await load()
      setDrawerMode(null)
      setEditingProvider(null)
      setProviderEditDraft(emptyProviderEditDraft)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '更新 AI 服务商失败')
    } finally {
      setPendingAction(null)
    }
  }

  const createModel = async () => {
    if (!modelDraft.provider_id || !modelDraft.model_key.trim() || !modelDraft.model_name.trim()) return setError('请选择服务商并填写模型标识与模型名称')
    setPendingAction('create-model')
    setError('')
    try {
      await api.post('/api/v1/admin/ai/models', {
        provider_id: modelDraft.provider_id,
        model_key: modelDraft.model_key.trim(),
        model_name: modelDraft.model_name.trim(),
        capabilities: modelDraft.capabilities.split(',').map((item) => item.trim()).filter(Boolean),
        enabled: false,
        pricing_version: modelDraft.pricing_version.trim(),
        dimensions: modelDraft.dimensions ? Number(modelDraft.dimensions) : null,
        config: { structured_output_mode: modelDraft.structured_output_mode },
      })
      setMessage('AI 模型已登记，默认保持停用状态。')
      setModelDraft({ ...emptyModelDraft, provider_id: providers[0]?.id || '' })
      await load()
      setDrawerMode(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '创建 AI 模型失败')
    } finally {
      setPendingAction(null)
    }
  }

  const updateModel = async () => {
    if (!editingModel) return
    if (!modelEditDraft.model_name.trim() || !modelEditDraft.capabilities.trim() || !modelEditDraft.pricing_version.trim()) return setError('请填写模型名称、能力和计价版本')
    setPendingAction('update-model')
    setError('')
    try {
      await api.patch<AiModel>(`/api/v1/admin/ai/models/${editingModel.id}`, {
        model_name: modelEditDraft.model_name.trim(),
        capabilities: modelEditDraft.capabilities.split(',').map((item) => item.trim()).filter(Boolean),
        pricing_version: modelEditDraft.pricing_version.trim(),
        dimensions: modelEditDraft.dimensions ? Number(modelEditDraft.dimensions) : null,
        config: { ...editingModel.config, structured_output_mode: modelEditDraft.structured_output_mode },
      })
      setMessage('AI 模型配置已更新。请重新执行连接测试。')
      await load()
      setDrawerMode(null)
      setEditingModel(null)
      setModelEditDraft(emptyModelEditDraft)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '更新 AI 模型失败')
    } finally {
      setPendingAction(null)
    }
  }

  const toggleProvider = async (provider: AiProvider) => {
    setPendingAction(`provider:${provider.id}`)
    setError('')
    try {
      await api.post(`/api/v1/admin/ai/providers/${provider.id}/${provider.enabled ? 'disable' : 'enable'}`)
      setMessage(provider.enabled ? 'AI 服务商已停用。' : 'AI 服务商已启用。')
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '更新 AI 服务商状态失败')
    } finally {
      setPendingAction(null)
    }
  }

  const openCredential = (provider: AiProvider) => {
    setCredentialProvider(provider)
    setCredentialDraft('')
    setError('')
    setMessage('')
    setDrawerMode('credential')
  }

  const replaceCredential = async () => {
    if (!credentialProvider) return
    if (!credentialDraft.trim()) return setError('请输入新的 env:// 环境变量引用。如需删除当前引用，请使用“清除引用”。')
    setPendingAction('credential')
    setError('')
    try {
      const updated = await api.patch<AiProvider>(`/api/v1/admin/ai/providers/${credentialProvider.id}`, { replace_credential_ref: credentialDraft.trim() })
      setMessage(updated.credential_configured ? '凭据引用已更新，后端已经解析到真实凭据。' : '凭据引用已更新，但后端尚未解析到对应真实凭据。')
      await load()
      setDrawerMode(null)
      setCredentialProvider(null)
      setCredentialDraft('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '更新凭据引用失败')
    } finally {
      setPendingAction(null)
    }
  }

  const clearCredential = async () => {
    if (!credentialProvider) return
    setPendingAction('credential-clear')
    setError('')
    try {
      await api.patch<AiProvider>(`/api/v1/admin/ai/providers/${credentialProvider.id}`, { replace_credential_ref: null })
      setMessage('凭据引用已清除。')
      await load()
      setDrawerMode(null)
      setCredentialProvider(null)
      setCredentialDraft('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '清除凭据引用失败')
    } finally {
      setPendingAction(null)
    }
  }

  const toggleModel = async (model: AiModel) => {
    setPendingAction(`model:${model.id}`)
    setError('')
    try {
      await api.post(`/api/v1/admin/ai/models/${model.id}/${model.enabled ? 'disable' : 'enable'}`)
      setMessage(model.enabled ? 'AI 模型已停用。' : 'AI 模型已启用。')
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '更新 AI 模型状态失败')
    } finally {
      setPendingAction(null)
    }
  }

  const testModel = async (model: AiModel) => {
    setPendingAction(`test:${model.id}`)
    setError('')
    setMessage('')
    try {
      const provider = providers.find((item) => item.id === model.provider_id)
      if (provider && !provider.credential_configured) {
        const state = credentialState(provider)
        setError(`${state.title}：${state.detail}`)
        return
      }
      const response = await api.post<{ invocation_id: string | null; status: string; error_code: string | null }>(
        `/api/v1/admin/ai/providers/${model.provider_id}/test`, { model_id: model.id },
      )
      if (response.status !== 'succeeded') {
        const suffix = response.invocation_id ? ` 调用记录：${response.invocation_id.slice(0, 8)}。` : ''
        setError(`${connectionFailureMessage(provider, model, response.error_code)}${suffix}`)
      } else {
        setMessage('连接测试通过：服务地址、凭据和当前模型能力均已完成一次真实请求验证。')
      }
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'AI 模型连接测试失败')
    } finally {
      setPendingAction(null)
    }
  }

  return <div className="operations-page">
    <ErrorBanner error={error || null}/>
    {message&&<div className="success-banner">{message}</div>}

    <section className="panel">
      <ResourceHeader title="AI 服务商" description="管理模型服务连接、服务地址、凭据引用和启用状态。真实 API Key 只存在于后端环境或受控 .env 中，页面不会回显 Secret。" actions={<><button onClick={() => void load()}>刷新</button><button className="primary" onClick={openProvider}>新建服务商</button></>}/>
      {providers.length===0 ? <Empty text="暂无 AI 服务商" helper="先登记一个服务商，再为它添加模型并进行连接测试。" action={<button className="primary" onClick={openProvider}>新建服务商</button>}/> : <div className="table-wrap"><table><thead><tr><th>服务商</th><th>类型</th><th>服务地址</th><th>状态</th><th>凭据状态</th><th>验证状态</th><th>模型数</th><th>最近调用 / 错误率</th><th>操作</th></tr></thead><tbody>{providers.map((provider) => {
        const credential = credentialState(provider)
        return <tr key={provider.id}>
          <td><strong>{provider.display_name}</strong><small className="technical-meta">{provider.provider_key}</small></td>
          <td>{providerTypeLabel[provider.provider_type]||provider.provider_type}</td>
          <td><span className="mono-break">{provider.base_url}</span></td>
          <td>{enabledLabel(provider.enabled)}</td>
          <td><strong>{credential.title}</strong><small className="technical-meta">{credential.detail}</small><small className="technical-meta">当前引用：{provider.credential_ref_masked || '—'}</small></td>
          <td>{validationStatusLabel[provider.validation_status]}</td>
          <td>{provider.model_count}</td>
          <td>{provider.last_invocation_at || '暂无'}<small className="technical-meta">错误率 {provider.error_rate === null ? '暂无' : `${(provider.error_rate * 100).toFixed(1)}%`}</small></td>
          <td><div className="actions action-cell"><button className="primary" disabled={Boolean(pendingAction)} onClick={() => void toggleProvider(provider)}>{pendingAction===`provider:${provider.id}`?'正在处理…':provider.enabled?'停用':'启用'}</button><button disabled={Boolean(pendingAction)} onClick={() => openProviderEdit(provider)}>编辑连接</button><button disabled={Boolean(pendingAction)} onClick={() => openCredential(provider)}>配置凭据引用</button></div></td>
        </tr>})}</tbody></table></div>}
    </section>

    <section className="panel">
      <ResourceHeader title="AI 模型" description="登记服务商提供的模型、能力与结构化输出方式。连接测试会按当前模型能力发起一次显式真实请求。" actions={<button className="primary" disabled={providers.length===0} title={providers.length===0?'请先创建 AI 服务商':''} onClick={openModel}>新建模型</button>}/>
      {providers.length===0&&<div className="prerequisite-hint">请先创建 AI 服务商，再登记模型。</div>}
      {models.length===0 ? <Empty text="暂无 AI 模型" helper="模型登记后，可在这里编辑、启停并进行连接测试。" action={providers.length>0?<button className="primary" onClick={openModel}>新建模型</button>:undefined}/> : <div className="table-wrap"><table><thead><tr><th>模型标识</th><th>模型名称</th><th>所属服务商</th><th>能力</th><th>结构化输出</th><th>计价版本</th><th>状态</th><th>操作</th></tr></thead><tbody>{models.map((model) => {
        const provider=providers.find((item)=>item.id===model.provider_id)
        return <tr key={model.id}><td><strong>{model.model_key}</strong></td><td>{model.model_name}</td><td>{provider?.display_name||'未知服务商'}</td><td>{model.capabilities.join(', ')}</td><td>{structuredOutputModeLabel(model)}</td><td>{model.pricing_version}</td><td>{enabledLabel(model.enabled)}</td><td><div className="actions action-cell"><button className="primary" disabled={Boolean(pendingAction)} onClick={() => void testModel(model)}>{pendingAction===`test:${model.id}`?'正在测试…':'连接测试'}</button><button disabled={Boolean(pendingAction)} onClick={() => openModelEdit(model)}>编辑模型</button><button disabled={Boolean(pendingAction)} onClick={() => void toggleModel(model)}>{pendingAction===`model:${model.id}`?'正在处理…':model.enabled?'停用':'启用'}</button></div></td></tr>
      })}</tbody></table></div>}
    </section>

    <Drawer open={drawerMode==='provider'} title="新建 AI 服务商" description="登记兼容服务的稳定标识、访问地址与凭据引用。创建后默认停用。" onClose={() => setDrawerMode(null)} footer={<><button disabled={pendingAction==='create-provider'} onClick={() => setDrawerMode(null)}>取消</button><button className="primary" disabled={pendingAction==='create-provider'} onClick={() => void createProvider()}>{pendingAction==='create-provider'?'正在创建…':'创建服务商'}</button></>}>
      <ErrorBanner error={error || null}/>
      <div className="drawer-section"><h3>连接信息</h3><p>服务商标识用于路由和审计，名称用于界面展示。</p><div className="form-grid"><label>服务商标识<input value={providerDraft.provider_key} onChange={(event) => setProviderDraft({ ...providerDraft, provider_key: event.target.value })}/></label><label>服务商名称<input value={providerDraft.display_name} onChange={(event) => setProviderDraft({ ...providerDraft, display_name: event.target.value })}/></label><label className="field-full">服务类型<select value={providerDraft.provider_type} onChange={(event) => setProviderDraft({ ...providerDraft, provider_type: event.target.value })}><option value="openai_compatible">OpenAI 兼容服务</option><option value="local_openai_compatible">本地 OpenAI 兼容服务</option></select></label><label className="field-full">服务地址（Base URL）<input value={providerDraft.base_url} onChange={(event) => setProviderDraft({ ...providerDraft, base_url: event.target.value })} placeholder="https://provider.example/v1"/></label></div></div>
      <div className="drawer-section"><h3>凭据引用（不是 API Key）</h3><p>这里只保存类似 env://AI_PROVIDER_KEY 的环境变量引用。真实 Secret 由进程环境、云端 Secret 或项目 .env 提供，页面不会保存或回显真实 API Key。</p><div className="form-grid"><label className="field-full">环境变量引用<input type="text" autoComplete="off" placeholder="例如 env://AI_PROVIDER_KEY" value={providerDraft.credential_ref} onChange={(event) => setProviderDraft({ ...providerDraft, credential_ref: event.target.value })}/><small>只支持 env://UPPER_CASE_NAME 格式。保存引用不等于后端已经解析到真实凭据。</small></label></div></div>
    </Drawer>

    <Drawer open={drawerMode==='provider-edit'} title="编辑 AI 服务商连接" description={editingProvider?`服务商：${editingProvider.display_name}`:undefined} onClose={() => { setDrawerMode(null); setEditingProvider(null); setProviderEditDraft(emptyProviderEditDraft) }} footer={<><button disabled={pendingAction==='update-provider'} onClick={() => { setDrawerMode(null); setEditingProvider(null); setProviderEditDraft(emptyProviderEditDraft) }}>取消</button><button className="primary" disabled={pendingAction==='update-provider'} onClick={() => void updateProvider()}>{pendingAction==='update-provider'?'正在保存…':'保存连接信息'}</button></>}>
      <ErrorBanner error={error || null}/>
      <div className="drawer-section"><h3>连接信息</h3><p>服务商标识与类型属于稳定身份，不在这里改动；名称和 Base URL 可以按实际服务配置更新。</p>{editingProvider&&<div className="form-grid"><label>服务商标识<input value={editingProvider.provider_key} disabled/></label><label>服务类型<input value={providerTypeLabel[editingProvider.provider_type]||editingProvider.provider_type} disabled/></label><label className="field-full">服务商名称<input value={providerEditDraft.display_name} onChange={(event) => setProviderEditDraft({ ...providerEditDraft, display_name: event.target.value })}/></label><label className="field-full">服务地址（Base URL）<input value={providerEditDraft.base_url} onChange={(event) => setProviderEditDraft({ ...providerEditDraft, base_url: event.target.value })} placeholder="https://provider.example/v1"/><small>修改后，新的连接测试和业务调用会使用该地址。</small></label></div>}</div>
    </Drawer>

    <Drawer open={drawerMode==='model'} title="新建 AI 模型" description="将服务商提供的模型登记到路由系统，并声明结构化输出方式。" onClose={() => setDrawerMode(null)} footer={<><button disabled={pendingAction==='create-model'} onClick={() => setDrawerMode(null)}>取消</button><button className="primary" disabled={pendingAction==='create-model'} onClick={() => void createModel()}>{pendingAction==='create-model'?'正在创建…':'创建模型'}</button></>}>
      <ErrorBanner error={error || null}/>
      <div className="drawer-section"><h3>模型归属</h3><div className="form-grid"><label className="field-full">所属服务商<select value={modelDraft.provider_id} onChange={(event) => setModelDraft({ ...modelDraft, provider_id: event.target.value })}><option value="">请选择</option>{providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.display_name} · {provider.provider_key}</option>)}</select></label><label>模型标识<input value={modelDraft.model_key} onChange={(event) => setModelDraft({ ...modelDraft, model_key: event.target.value })}/></label><label>服务商模型名称<input value={modelDraft.model_name} onChange={(event) => setModelDraft({ ...modelDraft, model_name: event.target.value })}/></label></div></div>
      <div className="drawer-section"><h3>模型能力</h3><div className="form-grid"><label className="field-full">模型能力<input placeholder="如 text_generation,structured_output" value={modelDraft.capabilities} onChange={(event) => setModelDraft({ ...modelDraft, capabilities: event.target.value })}/></label><label>结构化输出方式<select value={modelDraft.structured_output_mode} onChange={(event) => setModelDraft({ ...modelDraft, structured_output_mode: event.target.value as ModelDraft['structured_output_mode'] })}><option value="json_object">JSON Object（兼容性优先）</option><option value="json_schema">JSON Schema（厂商需明确支持）</option></select><small>OpenAI 兼容并不代表所有厂商都支持 JSON Schema。DeepSeek 等服务建议使用 JSON Object。</small></label><label>计价版本<input value={modelDraft.pricing_version} onChange={(event) => setModelDraft({ ...modelDraft, pricing_version: event.target.value })}/></label><label>向量维度<input type="number" value={modelDraft.dimensions} onChange={(event) => setModelDraft({ ...modelDraft, dimensions: event.target.value })}/></label></div></div>
    </Drawer>

    <Drawer open={drawerMode==='model-edit'} title="编辑 AI 模型" description={editingModel?`模型：${editingModel.model_key}`:undefined} onClose={() => { setDrawerMode(null); setEditingModel(null); setModelEditDraft(emptyModelEditDraft) }} footer={<><button disabled={pendingAction==='update-model'} onClick={() => { setDrawerMode(null); setEditingModel(null); setModelEditDraft(emptyModelEditDraft) }}>取消</button><button className="primary" disabled={pendingAction==='update-model'} onClick={() => void updateModel()}>{pendingAction==='update-model'?'正在保存…':'保存模型配置'}</button></>}>
      <ErrorBanner error={error || null}/>
      {editingModel&&<><div className="drawer-section"><h3>模型信息</h3><p>模型标识作为稳定引用保持只读；服务商模型名称和能力可以按真实厂商配置更新。</p><div className="form-grid"><label>模型标识<input value={editingModel.model_key} disabled/></label><label>服务商模型名称<input value={modelEditDraft.model_name} onChange={(event) => setModelEditDraft({ ...modelEditDraft, model_name: event.target.value })}/></label><label className="field-full">模型能力<input value={modelEditDraft.capabilities} onChange={(event) => setModelEditDraft({ ...modelEditDraft, capabilities: event.target.value })}/></label></div></div><div className="drawer-section"><h3>结构化输出与计价</h3><div className="form-grid"><label>结构化输出方式<select value={modelEditDraft.structured_output_mode} onChange={(event) => setModelEditDraft({ ...modelEditDraft, structured_output_mode: event.target.value as ModelEditDraft['structured_output_mode'] })}><option value="json_object">JSON Object（兼容性优先）</option><option value="json_schema">JSON Schema（厂商需明确支持）</option></select><small>若连接测试返回 INVALID_REQUEST，优先核对厂商是否支持当前 response_format。</small></label><label>计价版本<input value={modelEditDraft.pricing_version} onChange={(event) => setModelEditDraft({ ...modelEditDraft, pricing_version: event.target.value })}/></label><label>向量维度<input type="number" value={modelEditDraft.dimensions} onChange={(event) => setModelEditDraft({ ...modelEditDraft, dimensions: event.target.value })}/></label></div></div></>}
    </Drawer>

    <Drawer open={drawerMode==='credential'} title="配置凭据引用" description={credentialProvider?`服务商：${credentialProvider.display_name}`:undefined} onClose={() => { setDrawerMode(null); setCredentialProvider(null); setCredentialDraft('') }} footer={<><button disabled={Boolean(pendingAction)} onClick={() => { setDrawerMode(null); setCredentialProvider(null); setCredentialDraft('') }}>取消</button>{credentialProvider?.credential_ref_masked&&<button className="danger" disabled={Boolean(pendingAction)} onClick={() => void clearCredential()}>{pendingAction==='credential-clear'?'正在清除…':'清除引用'}</button>}<button className="primary" disabled={Boolean(pendingAction)||!credentialDraft.trim()} onClick={() => void replaceCredential()}>{pendingAction==='credential'?'正在保存…':'保存新引用'}</button></>}>
      <ErrorBanner error={error || null}/>
      <div className="drawer-section"><h3>当前凭据状态</h3>{credentialProvider&&<div className="notice"><strong>{credentialState(credentialProvider).title}</strong><div>{credentialState(credentialProvider).detail}</div><div>当前引用：{credentialProvider.credential_ref_masked || '未配置'}</div></div>}<p>为避免暴露基础设施中的 Secret 名称，后端不会回传 env:// 后面的真实环境变量名，因此编辑框不会自动回填。这里的空白不代表未配置。</p></div>
      <div className="drawer-section"><h3>更换环境变量引用</h3><p>只有需要更换引用时才填写新的 env://NAME。真实 Secret 继续放在进程环境、云端 Secret 或项目 .env 中。</p><div className="form-grid"><label className="field-full">新的环境变量引用<input type="text" autoComplete="off" placeholder="例如 env://DEEPSEEK_API_KEY" value={credentialDraft} onChange={(event) => setCredentialDraft(event.target.value)}/><small>输入框不会回显当前引用；保存会替换旧引用。删除旧引用请使用独立的“清除引用”按钮。</small></label></div></div>
    </Drawer>
  </div>
}
