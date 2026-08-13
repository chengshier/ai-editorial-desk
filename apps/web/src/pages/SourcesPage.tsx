import { useCallback, useEffect, useMemo, useState } from 'react'
import { AdminApi } from '../api'
import { Drawer, Empty, ErrorBanner, ResourceHeader } from '../components/common'
import { enabledLabel, sourceModeLabel, sourceStatusLabel } from '../uiLabels'
import type { Account, Definition, Instance, Source } from '../types'

const emptyForm = {
  connector_instance_id: '',
  name: '',
  source_type: 'rss',
  mode: 'feed',
  scope_key: '',
  external_ref: '',
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
      if (instancePage.items[0]) setForm((current) => current.connector_instance_id ? current : { ...current, connector_instance_id: instancePage.items[0].id })
      setPageError(null)
    } catch (e) {
      setPageError((e as Error).message)
    }
  }, [api])

  useEffect(() => { void load() }, [load])

  const resetForm = () => {
    setEditingId(null)
    setDrawerError(null)
    setForm({ ...emptyForm, connector_instance_id: instances[0]?.id || '' })
  }

  const openCreate = () => { resetForm(); setMessage(null); setDrawerOpen(true) }

  const save = async () => {
    if (!form.connector_instance_id) return setDrawerError('请先选择所属连接器实例')
    if (!form.name.trim()) return setDrawerError('请填写信源名称')
    setPendingAction('save')
    setDrawerError(null)
    try {
      if (editingId) {
        await api.patch(`/api/v1/admin/sources/${editingId}`, { name: form.name, external_ref: form.external_ref || null })
        setMessage('信源已更新。')
      } else {
        await api.post('/api/v1/admin/sources', { ...form, external_ref: form.external_ref || null, config: {}, enabled: true })
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
      <ResourceHeader title="信源" description="信源是实际被采集的数据入口。测试运行会先让你确认运行账号，不再由页面提交一个缺少账号的请求。" actions={<><button onClick={() => void load()}>刷新</button><button className="primary" disabled={instances.length===0} title={instances.length===0?'请先创建连接器实例':''} onClick={openCreate}>新建信源</button></>}/>
      {instances.length===0&&<div className="prerequisite-hint">当前没有可用连接器实例，请先在“连接器实例”页面完成实例配置。</div>}
      {sources.length===0 ? <Empty text="暂无信源" helper="创建信源后，可在这里测试采集、启停信源并查看作用范围。" action={instances.length>0?<button className="primary" onClick={openCreate}>新建信源</button>:undefined}/> : <div className="table-wrap"><table><thead><tr><th>名称</th><th>所属实例</th><th>来源类型</th><th>采集模式</th><th>运行准备</th><th>状态</th><th>操作</th></tr></thead><tbody>{sources.map((source) => {
        const instance = instances.find((item)=>item.id===source.connector_instance_id)
        const definition = instance ? definitions.find((item) => item.id === instance.definition_id) : null
        const requiresAccount = Boolean(definition?.capabilities.requires_account)
        const usableAccounts = accounts.filter((account) => account.connector_instance_id === source.connector_instance_id && account.status === 'healthy')
        return <tr key={source.id}>
          <td><strong>{source.name}</strong><small className="technical-meta">{source.scope_key}</small></td>
          <td>{instance?.name||'未知实例'}</td>
          <td>{source.source_type}</td>
          <td>{sourceModeLabel[source.mode]||source.mode}</td>
          <td><div className="status-stack"><span>{requiresAccount ? (usableAccounts.length ? `${usableAccounts.length} 个健康账号` : '缺少平台账号') : '无需平台账号'}</span>{requiresAccount&&usableAccounts.length===0&&<small>测试运行前必须补齐</small>}</div></td>
          <td>{source.enabled?enabledLabel(true):(sourceStatusLabel[source.status]||enabledLabel(false))}</td>
          <td><div className="actions action-cell"><button className="primary" disabled={Boolean(pendingAction)||!source.enabled} title={!source.enabled?'请先启用该信源':'确认账号后创建少量测试运行'} onClick={() => openTest(source)}>测试运行</button><button disabled={Boolean(pendingAction)} onClick={() => edit(source)}>编辑</button><details className="more-actions"><summary>更多</summary><button disabled={Boolean(pendingAction)} onClick={() => void toggle(source)}>{pendingAction===`toggle:${source.id}`?'正在处理…':source.enabled?'停用':'启用'}</button><button className="danger" disabled={Boolean(pendingAction)} onClick={() => void archive(source)}>{pendingAction===`archive:${source.id}`?'正在归档…':'归档'}</button></details></div>{requiresAccount&&usableAccounts.length===0&&onNavigate&&<button className="inline-link" onClick={() => onNavigate('risk')}>去配置平台账号</button>}</td>
        </tr>
      })}</tbody></table></div>}
    </section>

    <Drawer open={drawerOpen} title={editingId?'编辑信源':'新建信源'} description={editingId?'名称和外部引用可修改；来源类型、采集模式和作用范围沿用创建时配置。':'选择所属实例并定义采集入口、模式和作用范围。'} onClose={() => { setDrawerOpen(false); resetForm() }} footer={<><button disabled={pendingAction==='save'} onClick={() => { setDrawerOpen(false); resetForm() }}>取消</button><button className="primary" disabled={pendingAction==='save'} onClick={() => void save()}>{pendingAction==='save'?'正在保存…':editingId?'保存修改':'创建信源'}</button></>}>
      <ErrorBanner error={drawerError}/>
      <div className="drawer-section"><h3>来源归属</h3><p>先选择实际执行采集的连接器实例，再为该入口设置便于识别的名称。</p><div className="form-grid"><label className="field-full">所属实例<select disabled={Boolean(editingId)} value={form.connector_instance_id} onChange={(event) => setForm({ ...form, connector_instance_id: event.target.value })}><option value="">请选择实例</option>{instances.map((instance) => <option key={instance.id} value={instance.id}>{instance.name}</option>)}</select></label><label className="field-full">信源名称<input aria-label="信源名称" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如：B站科技热点"/></label></div></div>
      <div className="drawer-section"><h3>采集规则</h3><p>这些字段定义信源类型、采集方式和运行时作用范围；编辑已有信源时保持其原始身份不变。</p><div className="form-grid"><label>来源类型<input disabled={Boolean(editingId)} value={form.source_type} onChange={(event) => setForm({ ...form, source_type: event.target.value })}/></label><label>采集模式<select disabled={Boolean(editingId)} value={form.mode} onChange={(event) => setForm({ ...form, mode: event.target.value })}>{Object.entries(sourceModeLabel).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><label className="field-full">作用范围<input disabled={Boolean(editingId)} value={form.scope_key} onChange={(event) => setForm({ ...form, scope_key: event.target.value })} placeholder="用于区分采集范围的稳定标识"/></label><label className="field-full">外部引用<input value={form.external_ref} onChange={(event) => setForm({ ...form, external_ref: event.target.value })} placeholder="可选，例如 RSS URL 或外部来源引用"/></label></div></div>
    </Drawer>

    <Drawer open={testOpen} title="测试运行" description="确认本次测试使用的信源、账号和采集上限。dry-run 会发起真实采集请求，但不会写入原始信号。" onClose={() => setTestOpen(false)} footer={<><button disabled={pendingAction?.startsWith('run:')} onClick={() => setTestOpen(false)}>取消</button><button className="primary" disabled={Boolean(pendingAction)||!testSource||(testRequiresAccount&&!testAccountId)} onClick={() => void testRun()}>{pendingAction?.startsWith('run:')?'正在创建运行…':'开始测试运行'}</button></>}>
      <ErrorBanner error={testError}/>
      <div className="drawer-section"><h3>运行对象</h3><p>{testSource?.name || '当前信源'} · {testInstance?.name || ''}</p><div className="form-grid"><label className="field-full">信源<input readOnly value={testSource?.name || ''}/></label><label>单次采集上限<input type="number" min="1" max="100" value={testLimit} onChange={(event) => setTestLimit(Math.max(1, Math.min(100, Number(event.target.value) || 1)))}/></label></div></div>
      <div className="drawer-section"><h3>平台账号</h3><p>{testRequiresAccount ? '当前连接器要求平台账号。账号必须属于同一个连接器实例，并通过 CollectorRuntime 的状态与风险预检。' : '当前连接器无需平台账号，可直接测试。'}</p>{testRequiresAccount&&<div className="form-grid"><label className="field-full">运行账号<select value={testAccountId} onChange={(event) => { setTestAccountId(event.target.value); setTestError(null) }}><option value="">请选择健康账号</option>{testAccounts.map((account) => <option key={account.id} value={account.id}>{account.display_name} · {account.account_identifier}</option>)}</select></label></div>}{testRequiresAccount&&testAccounts.length===0&&<div className="prerequisite-hint"><span>当前实例没有健康的平台账号。</span>{onNavigate&&<button className="quiet-action" onClick={() => { setTestOpen(false); onNavigate('risk') }}>去账号 / 风险配置</button>}</div>}</div>
    </Drawer>
  </div>
}
