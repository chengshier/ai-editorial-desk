import { useCallback, useEffect, useMemo, useState } from 'react'
import { AdminApi } from '../api'
import { Drawer, Empty, ErrorBanner, ResourceHeader } from '../components/common'
import { enabledLabel, sourceModeLabel, sourceStatusLabel } from '../uiLabels'
import type { Account, Definition, Instance, Source } from '../types'

const emptyForm = {
  connector_instance_id: '',
  name: '',
  source_type: '',
  mode: '',
  scope_key: '',
  external_ref: '',
}

const targetCopy: Record<string, { label: string; placeholder: string; helper: string; required: boolean }> = {
  search: { label: '搜索关键词', placeholder: '例如：AI Agent', helper: '一个搜索信源对应一个稳定关键词。需要多个关键词时，请分别创建多个信源，便于独立维护检查点与运行历史。', required: true },
  account: { label: '创作者 ID / URL', placeholder: '填写平台创作者 ID 或主页 URL', helper: '该目标用于账号 / 创作者采集。', required: true },
  detail: { label: '内容 ID / URL', placeholder: '填写内容 ID 或详情页 URL', helper: '该目标用于内容详情采集。', required: true },
  comments: { label: '内容 ID / URL', placeholder: '填写需要采集评论的内容 ID 或 URL', helper: '该目标用于评论采集，仍受评论预算与风险规则限制。', required: true },
  feed: { label: 'Feed URL', placeholder: 'https://example.com/feed.xml', helper: '填写该信源实际读取的 RSS / Atom 地址。', required: true },
  hotlist: { label: '热榜目标（可选）', placeholder: '留空时使用实例默认热榜来源', helper: '公开热榜通常由实例配置决定，只有实现明确要求时才填写。', required: false },
  manual_import: { label: '导入目标（可选）', placeholder: '手工导入通常在执行时指定 URL', helper: '手工导入的实际 URL 可在执行动作中提供。', required: false },
}

function supportedModes(definition: Definition | null | undefined): string[] {
  if (!definition) return []
  const declared = definition.capabilities.allowed_modes
  if (Array.isArray(declared)) return declared.filter((item): item is string => typeof item === 'string')
  return Object.keys(sourceModeLabel).filter((mode) => definition.capabilities[mode] === true)
}

function scopeKey(mode: string, target: string, name: string): string {
  const stableTarget = target.trim() || name.trim()
  return `${mode}:${stableTarget}`.slice(0, 500)
}

export function SourcesPage({ api, onNavigate }: { api: AdminApi; onNavigate?: (page: 'runs' | 'risk') => void }) {
  const [sources, setSources] = useState<Source[]>([])
  const [instances, setInstances] = useState<Instance[]>([])
  const [definitions, setDefinitions] = useState<Definition[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [editingId, setEditingId] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [testOpen, setTestOpen] = useState(false)
  const [testSourceId, setTestSourceId] = useState('')
  const [testAccountId, setTestAccountId] = useState('')
  const [testLimit, setTestLimit] = useState(5)
  const [message, setMessage] = useState<string | null>(null)
  const [form, setForm] = useState(emptyForm)
  const [pageError, setPageError] = useState<string | null>(null)
  const [drawerError, setDrawerError] = useState<string | null>(null)
  const [testError, setTestError] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<string | null>(null)

  const formInstance = useMemo(() => instances.find((item) => item.id === form.connector_instance_id) || null, [instances, form.connector_instance_id])
  const formDefinition = useMemo(() => formInstance ? definitions.find((item) => item.id === formInstance.definition_id) || null : null, [definitions, formInstance])
  const formModes = useMemo(() => supportedModes(formDefinition), [formDefinition])
  const target = targetCopy[form.mode] || { label: '采集目标 / 外部引用', placeholder: '填写该模式需要的外部目标', helper: '该值会作为本信源运行时的明确采集目标。', required: false }

  const testSource = useMemo(() => sources.find((item) => item.id === testSourceId) || null, [sources, testSourceId])
  const testInstance = useMemo(() => testSource ? instances.find((item) => item.id === testSource.connector_instance_id) || null : null, [instances, testSource])
  const testDefinition = useMemo(() => testInstance ? definitions.find((item) => item.id === testInstance.definition_id) || null : null, [definitions, testInstance])
  const testRequiresAccount = Boolean(testDefinition?.capabilities.requires_account)
  const testAccounts = useMemo(() => testInstance ? accounts.filter((item) => item.connector_instance_id === testInstance.id && item.status === 'healthy') : [], [accounts, testInstance])

  const load = useCallback(async () => {
    try {
      const [sourcePage, instancePage, definitionPage, accountPage] = await Promise.all([
        api.page<Source>('/api/v1/admin/sources?page_size=100'),
        api.page<Instance>('/api/v1/admin/connector-instances?page_size=100'),
        api.page<Definition>('/api/v1/admin/connector-definitions?page_size=100'),
        api.page<Account>('/api/v1/admin/platform-accounts?page_size=100'),
      ])
      setSources(sourcePage.items)
      setInstances(instancePage.items)
      setDefinitions(definitionPage.items)
      setAccounts(accountPage.items)
      if (instancePage.items[0]) {
        setForm((current) => {
          if (current.connector_instance_id) return current
          const instance = instancePage.items[0]
          const definition = definitionPage.items.find((item) => item.id === instance.definition_id)
          const modes = supportedModes(definition)
          return { ...emptyForm, connector_instance_id: instance.id, source_type: definition?.connector_type || instance.connector_type, mode: modes[0] || '' }
        })
      }
      setPageError(null)
    } catch (e) {
      setPageError((e as Error).message)
    }
  }, [api])

  useEffect(() => { void load() }, [load])

  const formForInstance = (instanceId: string) => {
    const instance = instances.find((item) => item.id === instanceId)
    const definition = instance ? definitions.find((item) => item.id === instance.definition_id) : null
    const modes = supportedModes(definition)
    return {
      ...emptyForm,
      connector_instance_id: instanceId,
      source_type: definition?.connector_type || instance?.connector_type || '',
      mode: modes[0] || '',
    }
  }

  const resetForm = () => {
    setEditingId(null)
    setDrawerError(null)
    setForm(instances[0] ? formForInstance(instances[0].id) : emptyForm)
  }

  const openCreate = () => { resetForm(); setMessage(null); setDrawerOpen(true) }

  const save = async () => {
    if (!form.connector_instance_id || !formDefinition) return setDrawerError('请先选择所属连接器实例')
    if (!form.name.trim()) return setDrawerError('请填写信源名称')
    if (!form.mode) return setDrawerError('请选择采集模式')
    if (target.required && !form.external_ref.trim()) return setDrawerError(`请填写${target.label}`)
    setPendingAction('save')
    setDrawerError(null)
    try {
      if (editingId) {
        await api.patch(`/api/v1/admin/sources/${editingId}`, { name: form.name.trim(), external_ref: form.external_ref.trim() || null })
        setMessage('信源已更新。')
      } else {
        await api.post('/api/v1/admin/sources', {
          connector_instance_id: form.connector_instance_id,
          name: form.name.trim(),
          source_type: formDefinition.connector_type,
          mode: form.mode,
          scope_key: scopeKey(form.mode, form.external_ref, form.name),
          external_ref: form.external_ref.trim() || null,
          config: {},
          enabled: true,
        })
        setMessage('信源已创建。')
      }
      await load()
      setDrawerOpen(false)
      resetForm()
    } catch (e) {
      setDrawerError((e as Error).message)
    } finally {
      setPendingAction(null)
    }
  }

  const edit = (source: Source) => {
    setEditingId(source.id)
    setForm({
      connector_instance_id: source.connector_instance_id,
      name: source.name,
      source_type: source.source_type,
      mode: source.mode,
      scope_key: source.scope_key,
      external_ref: source.external_ref || '',
    })
    setMessage(null)
    setDrawerError(null)
    setDrawerOpen(true)
  }

  const toggle = async (source: Source) => {
    setPendingAction(`toggle:${source.id}`)
    setPageError(null)
    try {
      await api.patch(`/api/v1/admin/sources/${source.id}`, { enabled: !source.enabled })
      setMessage(source.enabled ? '信源已停用。' : '信源已启用。')
      await load()
    } catch (e) {
      setPageError((e as Error).message)
    } finally {
      setPendingAction(null)
    }
  }

  const archive = async (source: Source) => {
    if (!window.confirm('归档信源？历史原始信号不会删除。')) return
    setPendingAction(`archive:${source.id}`)
    setPageError(null)
    try {
      await api.post(`/api/v1/admin/sources/${source.id}/archive`)
      setMessage('信源已归档。')
      await load()
    } catch (e) {
      setPageError((e as Error).message)
    } finally {
      setPendingAction(null)
    }
  }

  const openTest = (source: Source) => {
    const matchingAccounts = accounts.filter((item) => item.connector_instance_id === source.connector_instance_id && item.status === 'healthy')
    setTestSourceId(source.id)
    setTestAccountId(matchingAccounts[0]?.id || '')
    setTestLimit(5)
    setTestError(null)
    setMessage(null)
    setTestOpen(true)
  }

  const testRun = async () => {
    if (!testSource) return setTestError('信源不存在，请关闭后刷新页面重试。')
    if (!testSource.enabled) return setTestError('该信源当前已停用，请先启用后再测试运行。')
    if (testRequiresAccount && !testAccountId) return setTestError('该连接器运行需要平台账号。请先选择健康账号；没有可选账号时请前往“账号 / 风险”配置。')
    setPendingAction(`run:${testSource.id}`)
    setTestError(null)
    try {
      const result = await api.post<{ run_id: string; status: string }>(
        `/api/v1/admin/connector-instances/${testSource.connector_instance_id}/test-runs`,
        { source_id: testSource.id, platform_account_id: testAccountId || null, requested_limit: testLimit, dry_run: true },
      )
      setMessage(`测试运行已创建：${result.status} / ${result.run_id}`)
      setTestOpen(false)
    } catch (e) {
      setTestError((e as Error).message)
    } finally {
      setPendingAction(null)
    }
  }

  return <div className="operations-page">
    <ErrorBanner error={pageError}/>
    {message && <div className="success-banner"><span>{message}</span>{message.includes('运行') && onNavigate && <button className="quiet-action" onClick={() => onNavigate('runs')}>查看运行记录</button>}</div>}

    <section className="panel">
      <ResourceHeader title="信源" description="信源回答“具体采什么”。每个信源绑定一个连接器实例和一个稳定采集目标，检查点、预算与运行历史会按信源独立维护。" actions={<><button onClick={() => void load()}>刷新</button><button className="primary" disabled={instances.length===0} title={instances.length===0?'请先创建连接器实例':''} onClick={openCreate}>新建信源</button></>}/>
      {instances.length===0&&<div className="prerequisite-hint">当前没有可用连接器实例，请先在“连接器实例”页面完成实例配置。</div>}
      {sources.length===0 ? <Empty text="暂无信源" helper="创建信源后，可在这里测试采集、启停信源并查看运行准备状态。" action={instances.length>0?<button className="primary" onClick={openCreate}>新建信源</button>:undefined}/> : <div className="table-wrap"><table><thead><tr><th>名称 / 目标</th><th>所属实例</th><th>采集模式</th><th>运行准备</th><th>状态</th><th>操作</th></tr></thead><tbody>{sources.map((source) => {
        const instance = instances.find((item)=>item.id===source.connector_instance_id)
        const definition = instance ? definitions.find((item) => item.id === instance.definition_id) : null
        const requiresAccount = Boolean(definition?.capabilities.requires_account)
        const usableAccounts = accounts.filter((account) => account.connector_instance_id === source.connector_instance_id && account.status === 'healthy')
        const sourceTarget = targetCopy[source.mode]
        return <tr key={source.id}>
          <td><strong>{source.name}</strong><small className="technical-meta">{sourceTarget?.label || '采集目标'} · {source.external_ref || '使用实例默认配置'}</small></td>
          <td>{instance?.name||'未知实例'}<small className="technical-meta">{definition?.display_name || source.source_type}</small></td>
          <td>{sourceModeLabel[source.mode]||source.mode}</td>
          <td><div className="status-stack"><span>{requiresAccount ? (usableAccounts.length ? `${usableAccounts.length} 个健康账号` : '缺少平台账号') : '无需平台账号'}</span>{requiresAccount&&usableAccounts.length===0&&<small>测试运行前必须补齐</small>}</div></td>
          <td>{source.enabled?enabledLabel(true):(sourceStatusLabel[source.status]||enabledLabel(false))}</td>
          <td><div className="actions action-cell"><button className="primary" disabled={Boolean(pendingAction)||!source.enabled} title={!source.enabled?'请先启用该信源':'确认账号后创建少量测试运行'} onClick={() => openTest(source)}>测试运行</button><button disabled={Boolean(pendingAction)} onClick={() => edit(source)}>编辑</button><details className="more-actions"><summary>更多</summary><button disabled={Boolean(pendingAction)} onClick={() => void toggle(source)}>{pendingAction===`toggle:${source.id}`?'正在处理…':source.enabled?'停用':'启用'}</button><button className="danger" disabled={Boolean(pendingAction)} onClick={() => void archive(source)}>{pendingAction===`archive:${source.id}`?'正在归档…':'归档'}</button></details></div>{requiresAccount&&usableAccounts.length===0&&onNavigate&&<button className="inline-link" onClick={() => onNavigate('risk')}>去配置平台账号</button>}</td>
        </tr>
      })}</tbody></table></div>}
    </section>

    <Drawer open={drawerOpen} title={editingId?'编辑信源':'新建信源'} description={editingId?'修改名称和实际采集目标；所属实例和采集模式保持不变。':'先选择运行实例与采集模式，再填写这个信源真正要采集的目标。'} onClose={() => { setDrawerOpen(false); resetForm() }} footer={<><button disabled={pendingAction==='save'} onClick={() => { setDrawerOpen(false); resetForm() }}>取消</button><button className="primary" disabled={pendingAction==='save'} onClick={() => void save()}>{pendingAction==='save'?'正在保存…':editingId?'保存修改':'创建信源'}</button></>}>
      <ErrorBanner error={drawerError}/>
      <div className="drawer-section"><h3>来源归属</h3><p>连接器实例决定“用什么能力运行”，信源决定“具体采什么”。</p><div className="form-grid"><label className="field-full">所属实例<select disabled={Boolean(editingId)} value={form.connector_instance_id} onChange={(event) => { setForm(formForInstance(event.target.value)); setDrawerError(null) }}><option value="">请选择实例</option>{instances.map((instance) => <option key={instance.id} value={instance.id}>{instance.name}</option>)}</select></label><label className="field-full">连接器能力<input readOnly value={formDefinition ? `${formDefinition.display_name} · ${formDefinition.connector_type}` : '请选择实例'}/></label><label className="field-full">信源名称<input aria-label="信源名称" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如：B站 · AI Agent 热点"/></label></div></div>
      <div className="drawer-section"><h3>采集目标</h3><p>具体关键词、创作者或内容目标属于信源，不再放在连接器实例配置中。</p><div className="form-grid"><label className="field-full">采集模式<select disabled={Boolean(editingId)} value={form.mode} onChange={(event) => { setForm({ ...form, mode: event.target.value, external_ref: '' }); setDrawerError(null) }}><option value="">请选择模式</option>{formModes.map((mode)=><option key={mode} value={mode}>{sourceModeLabel[mode]||mode}</option>)}</select></label><label className="field-full">{target.label}{target.required ? ' *' : ''}<input value={form.external_ref} onChange={(event) => { setForm({ ...form, external_ref: event.target.value }); setDrawerError(null) }} placeholder={target.placeholder}/><small>{target.helper}</small></label>{editingId&&<div className="field-full technical-meta">内部作用域：{form.scope_key}</div>}</div></div>
    </Drawer>

    <Drawer open={testOpen} title="测试运行" description="确认本次测试使用的信源、账号和采集上限。dry-run 会发起真实采集请求，但不会写入原始信号。" onClose={() => setTestOpen(false)} footer={<><button disabled={pendingAction?.startsWith('run:')} onClick={() => setTestOpen(false)}>取消</button><button className="primary" disabled={Boolean(pendingAction)||!testSource||(testRequiresAccount&&!testAccountId)} onClick={() => void testRun()}>{pendingAction?.startsWith('run:')?'正在创建运行…':'开始测试运行'}</button></>}>
      <ErrorBanner error={testError}/>
      <div className="drawer-section"><h3>运行对象</h3><p>{testSource?.name || '当前信源'} · {testInstance?.name || ''}</p><div className="form-grid"><label className="field-full">采集目标<input readOnly value={testSource?.external_ref || '使用实例默认配置'}/></label><label>采集模式<input readOnly value={testSource ? (sourceModeLabel[testSource.mode] || testSource.mode) : ''}/></label><label>单次采集上限<input type="number" min="1" max="100" value={testLimit} onChange={(event) => setTestLimit(Math.max(1, Math.min(100, Number(event.target.value) || 1)))}/></label></div></div>
      <div className="drawer-section"><h3>平台账号</h3><p>{testRequiresAccount ? '当前连接器要求平台账号。账号必须属于同一个连接器实例，并通过 CollectorRuntime 的状态与风险预检。' : '当前连接器无需平台账号，可直接测试。'}</p>{testRequiresAccount&&<div className="form-grid"><label className="field-full">运行账号<select value={testAccountId} onChange={(event) => { setTestAccountId(event.target.value); setTestError(null) }}><option value="">请选择健康账号</option>{testAccounts.map((account) => <option key={account.id} value={account.id}>{account.display_name} · {account.account_identifier}</option>)}</select></label></div>}{testRequiresAccount&&testAccounts.length===0&&<div className="prerequisite-hint"><span>当前实例没有健康的平台账号。</span>{onNavigate&&<button className="quiet-action" onClick={() => { setTestOpen(false); onNavigate('risk') }}>去账号 / 风险配置</button>}</div>}</div>
    </Drawer>
  </div>
}