import { useCallback, useEffect, useState } from 'react'
import type { AdminApi } from '../api'
import type { AiModel, AiProvider } from '../aiTypes'
import { Drawer, Empty, ErrorBanner, ResourceHeader } from '../components/common'
import { enabledLabel, providerTypeLabel, validationStatusLabel } from '../uiLabels'

type Props = { api: AdminApi }
type DrawerMode = 'provider' | 'model' | 'credential' | null

const emptyProviderDraft = {
  provider_key: '', display_name: '', provider_type: 'openai_compatible',
  base_url: '', credential_ref: '',
}
const emptyModelDraft = {
  provider_id: '', model_key: '', model_name: '', capabilities: 'text_generation',
  pricing_version: 'unpriced-v1', dimensions: '', structured_output_mode: 'json_schema',
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
  const [providerDraft, setProviderDraft] = useState(emptyProviderDraft)
  const [modelDraft, setModelDraft] = useState(emptyModelDraft)

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
    setDrawerMode('provider')
  }

  const openModel = () => {
    setModelDraft({ ...emptyModelDraft, provider_id: providers[0]?.id || '' })
    setError('')
    setDrawerMode('model')
  }

  const createProvider = async () => {
    if (!providerDraft.provider_key.trim() || !providerDraft.display_name.trim() || !providerDraft.base_url.trim()) return setError('请填写服务商标识、名称和服务地址')
    setPendingAction('create-provider')
    setError('')
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
      setMessage('AI 服务商已创建，默认保持停用状态。')
      setProviderDraft(emptyProviderDraft)
      await load()
      setDrawerMode(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '创建 AI 服务商失败')
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
        model_key: modelDraft.model_key,
        model_name: modelDraft.model_name,
        capabilities: modelDraft.capabilities.split(',').map((item) => item.trim()).filter(Boolean),
        enabled: false,
        pricing_version: modelDraft.pricing_version,
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
    setDrawerMode('credential')
  }

  const replaceCredential = async () => {
    if (!credentialProvider) return
    setPendingAction('credential')
    setError('')
    try {
      await api.patch(`/api/v1/admin/ai/providers/${credentialProvider.id}`, { replace_credential_ref: credentialDraft.trim() || null })
      setMessage('凭据引用已更新；页面不会读取或显示真实 Secret。')
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
    try {
      const response = await api.post<{ status: string; error_code: string | null }>(
        `/api/v1/admin/ai/providers/${model.provider_id}/test`, { model_id: model.id },
      )
      setMessage(response.error_code ? `连接测试完成：${response.status} · ${response.error_code}` : `连接测试完成：${response.status}`)
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
      <ResourceHeader title="AI 服务商" description="管理模型服务连接、凭据引用和启用状态。创建服务商时只登记连接信息，不会自动启用。" actions={<><button onClick={() => void load()}>刷新</button><button className="primary" onClick={openProvider}>新建服务商</button></>}/>
      {providers.length===0 ? <Empty text="暂无 AI 服务商" helper="先登记一个服务商，再为它添加模型并进行连接测试。" action={<button className="primary" onClick={openProvider}>新建服务商</button>}/> : <div className="table-wrap"><table><thead><tr><th>服务商</th><th>类型</th><th>状态</th><th>凭据</th><th>验证状态</th><th>模型数</th><th>最近调用 / 错误率</th><th>操作</th></tr></thead><tbody>{providers.map((provider) => <tr key={provider.id}>
        <td><strong>{provider.display_name}</strong><small className="technical-meta">{provider.provider_key}</small></td>
        <td>{providerTypeLabel[provider.provider_type]||provider.provider_type}</td>
        <td>{enabledLabel(provider.enabled)}</td>
        <td>{provider.credential_configured ? '已配置' : '未配置'}<small className="technical-meta">{provider.credential_ref_masked || '—'}</small></td>
        <td>{validationStatusLabel[provider.validation_status]}</td>
        <td>{provider.model_count}</td>
        <td>{provider.last_invocation_at || '暂无'}<small className="technical-meta">错误率 {provider.error_rate === null ? '暂无' : `${(provider.error_rate * 100).toFixed(1)}%`}</small></td>
        <td><div className="actions action-cell"><button className="primary" disabled={Boolean(pendingAction)} onClick={() => void toggleProvider(provider)}>{pendingAction===`provider:${provider.id}`?'正在处理…':provider.enabled?'停用':'启用'}</button><button disabled={Boolean(pendingAction)} onClick={() => openCredential(provider)}>更换凭据</button></div></td>
      </tr>)}</tbody></table></div>}
    </section>

    <section className="panel">
      <ResourceHeader title="AI 模型" description="登记服务商提供的模型与结构化输出方式。连接测试是显式操作，不会自动触发业务调用。" actions={<button className="primary" disabled={providers.length===0} title={providers.length===0?'请先创建 AI 服务商':''} onClick={openModel}>新建模型</button>}/>
      {providers.length===0&&<div className="prerequisite-hint">请先创建 AI 服务商，再登记模型。</div>}
      {models.length===0 ? <Empty text="暂无 AI 模型" helper="模型登记后，可在这里启停并进行连接测试。" action={providers.length>0?<button className="primary" onClick={openModel}>新建模型</button>:undefined}/> : <div className="table-wrap"><table><thead><tr><th>模型标识</th><th>模型名称</th><th>所属服务商</th><th>能力</th><th>计价版本</th><th>状态</th><th>操作</th></tr></thead><tbody>{models.map((model) => {
        const provider=providers.find((item)=>item.id===model.provider_id)
        return <tr key={model.id}><td><strong>{model.model_key}</strong></td><td>{model.model_name}</td><td>{provider?.display_name||'未知服务商'}</td><td>{model.capabilities.join(', ')}</td><td>{model.pricing_version}</td><td>{enabledLabel(model.enabled)}</td><td><div className="actions action-cell"><button className="primary" disabled={Boolean(pendingAction)} onClick={() => void testModel(model)}>{pendingAction===`test:${model.id}`?'正在测试…':'连接测试'}</button><button disabled={Boolean(pendingAction)} onClick={() => void toggleModel(model)}>{pendingAction===`model:${model.id}`?'正在处理…':model.enabled?'停用':'启用'}</button></div></td></tr>
      })}</tbody></table></div>}
    </section>

    <Drawer open={drawerMode==='provider'} title="新建 AI 服务商" description="登记兼容服务的稳定标识、访问地址与凭据引用。创建后默认停用。" onClose={() => setDrawerMode(null)} footer={<><button disabled={pendingAction==='create-provider'} onClick={() => setDrawerMode(null)}>取消</button><button className="primary" disabled={pendingAction==='create-provider'} onClick={() => void createProvider()}>{pendingAction==='create-provider'?'正在创建…':'创建服务商'}</button></>}>
      <div className="drawer-section"><h3>连接信息</h3><p>服务商标识用于路由和审计，名称用于界面展示。</p><div className="form-grid"><label>服务商标识<input value={providerDraft.provider_key} onChange={(event) => setProviderDraft({ ...providerDraft, provider_key: event.target.value })}/></label><label>服务商名称<input value={providerDraft.display_name} onChange={(event) => setProviderDraft({ ...providerDraft, display_name: event.target.value })}/></label><label className="field-full">服务类型<select value={providerDraft.provider_type} onChange={(event) => setProviderDraft({ ...providerDraft, provider_type: event.target.value })}><option value="openai_compatible">OpenAI 兼容服务</option><option value="local_openai_compatible">本地 OpenAI 兼容服务</option></select></label><label className="field-full">服务地址（Base URL）<input value={providerDraft.base_url} onChange={(event) => setProviderDraft({ ...providerDraft, base_url: event.target.value })} placeholder="https://provider.example/v1"/></label></div></div>
      <div className="drawer-section"><h3>凭据引用</h3><p>这里只保存 opaque credential_ref，不读取或显示真实 Secret。</p><div className="form-grid"><label className="field-full">凭据引用<input type="password" autoComplete="off" placeholder="例如 env://AI_PROVIDER_KEY" value={providerDraft.credential_ref} onChange={(event) => setProviderDraft({ ...providerDraft, credential_ref: event.target.value })}/></label></div></div>
    </Drawer>

    <Drawer open={drawerMode==='model'} title="新建 AI 模型" description="将服务商提供的模型登记到路由系统，并声明结构化输出方式。" onClose={() => setDrawerMode(null)} footer={<><button disabled={pendingAction==='create-model'} onClick={() => setDrawerMode(null)}>取消</button><button className="primary" disabled={pendingAction==='create-model'} onClick={() => void createModel()}>{pendingAction==='create-model'?'正在创建…':'创建模型'}</button></>}>
      <div className="drawer-section"><h3>模型归属</h3><div className="form-grid"><label className="field-full">所属服务商<select value={modelDraft.provider_id} onChange={(event) => setModelDraft({ ...modelDraft, provider_id: event.target.value })}><option value="">请选择</option>{providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.display_name} · {provider.provider_key}</option>)}</select></label><label>模型标识<input value={modelDraft.model_key} onChange={(event) => setModelDraft({ ...modelDraft, model_key: event.target.value })}/></label><label>服务商模型名称<input value={modelDraft.model_name} onChange={(event) => setModelDraft({ ...modelDraft, model_name: event.target.value })}/></label></div></div>
      <div className="drawer-section"><h3>模型能力</h3><div className="form-grid"><label className="field-full">模型能力<input placeholder="如 text_generation,structured_output" value={modelDraft.capabilities} onChange={(event) => setModelDraft({ ...modelDraft, capabilities: event.target.value })}/></label><label>结构化输出方式<select value={modelDraft.structured_output_mode} onChange={(event) => setModelDraft({ ...modelDraft, structured_output_mode: event.target.value })}><option value="json_schema">JSON Schema</option><option value="json_object">JSON Object</option></select></label><label>计价版本<input value={modelDraft.pricing_version} onChange={(event) => setModelDraft({ ...modelDraft, pricing_version: event.target.value })}/></label><label>向量维度<input type="number" value={modelDraft.dimensions} onChange={(event) => setModelDraft({ ...modelDraft, dimensions: event.target.value })}/></label></div></div>
    </Drawer>

    <Drawer open={drawerMode==='credential'} title="更换凭据引用" description={credentialProvider?`服务商：${credentialProvider.display_name}`:undefined} onClose={() => { setDrawerMode(null); setCredentialProvider(null); setCredentialDraft('') }} footer={<><button disabled={pendingAction==='credential'} onClick={() => setDrawerMode(null)}>取消</button><button className="primary" disabled={pendingAction==='credential'} onClick={() => void replaceCredential()}>{pendingAction==='credential'?'正在保存…':'保存凭据引用'}</button></>}>
      <div className="drawer-section"><h3>新的凭据引用</h3><p>不会回显旧凭据。留空表示按后端支持的语义清除引用。</p><div className="form-grid"><label className="field-full">凭据引用<input type="password" autoComplete="off" placeholder="例如 env://AI_PROVIDER_KEY" value={credentialDraft} onChange={(event) => setCredentialDraft(event.target.value)}/></label></div></div>
    </Drawer>
  </div>
}
