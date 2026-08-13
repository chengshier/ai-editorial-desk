import { useCallback, useEffect, useMemo, useState } from 'react'
import { AdminApi } from '../api'
import { Drawer, Empty, ErrorBanner, ResourceHeader } from '../components/common'
import { enabledLabel, sourceStatusLabel } from '../uiLabels'
import { SchemaForm, validateSchemaValue } from '../components/SchemaForm'
import type { Account, Definition, Instance, Source } from '../types'

export function InstancesPage({ api, onNavigate }: { api: AdminApi; onNavigate?: (page: 'runs' | 'risk') => void }) {
  const [instances, setInstances] = useState<Instance[]>([])
  const [definitions, setDefinitions] = useState<Definition[]>([])
  const [sources, setSources] = useState<Source[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [definitionId, setDefinitionId] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [config, setConfig] = useState<Record<string, unknown>>({})
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [runOpen, setRunOpen] = useState(false)
  const [runInstanceId, setRunInstanceId] = useState('')
  const [runSourceId, setRunSourceId] = useState('')
  const [runAccountId, setRunAccountId] = useState('')
  const [runLimit, setRunLimit] = useState(5)
  const [runDry, setRunDry] = useState(true)
  const [message, setMessage] = useState<string | null>(null)
  const [pageError, setPageError] = useState<string | null>(null)
  const [drawerError, setDrawerError] = useState<string | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<string | null>(null)

  const selected = useMemo(
    () => definitions.find((item) => item.id === definitionId),
    [definitions, definitionId],
  )
  const runInstance = useMemo(() => instances.find((item) => item.id === runInstanceId) || null, [instances, runInstanceId])
  const runDefinition = useMemo(() => runInstance ? definitions.find((item) => item.id === runInstance.definition_id) || null : null, [definitions, runInstance])
  const runSources = useMemo(() => sources.filter((item) => item.connector_instance_id === runInstanceId && item.enabled), [sources, runInstanceId])
  const runAccounts = useMemo(() => accounts.filter((item) => item.connector_instance_id === runInstanceId && item.status === 'healthy'), [accounts, runInstanceId])
  const runRequiresAccount = Boolean(runDefinition?.capabilities.requires_account)

  const load = useCallback(async () => {
    try {
      const [instancePage, definitionPage, sourcePage, accountPage] = await Promise.all([
        api.page<Instance>('/api/v1/admin/connector-instances?page_size=100'),
        api.page<Definition>('/api/v1/admin/connector-definitions?page_size=100'),
        api.page<Source>('/api/v1/admin/sources?page_size=100'),
        api.page<Account>('/api/v1/admin/platform-accounts?page_size=100'),
      ])
      setInstances(instancePage.items)
      setDefinitions(definitionPage.items)
      setSources(sourcePage.items)
      setAccounts(accountPage.items)
      if (definitionPage.items[0]) setDefinitionId((current) => current || definitionPage.items[0].id)
      setPageError(null)
    } catch (e) {
      setPageError((e as Error).message)
    }
  }, [api])

  useEffect(() => { void load() }, [load])

  const resetForm = () => {
    setEditingId(null)
    setName('')
    setConfig({})
    setDrawerError(null)
    if (definitions[0]) setDefinitionId(definitions[0].id)
  }
  const closeDrawer = () => { setDrawerOpen(false); resetForm() }
  const openCreate = () => { resetForm(); setMessage(null); setDrawerOpen(true) }

  const save = async () => {
    if (!selected || !name.trim()) return setDrawerError('请选择连接器类型并填写实例名称')
    if (Object.keys(validateSchemaValue(selected.config_schema, config, selected.ui_schema)).length) return setDrawerError('配置未通过表单校验，请检查必填项与字段范围')
    setPendingAction('save')
    setDrawerError(null)
    try {
      if (editingId) {
        await api.patch(`/api/v1/admin/connector-instances/${editingId}`, { name, config })
        setMessage('连接器实例已更新。')
      } else {
        await api.post('/api/v1/admin/connector-instances', { definition_id: selected.id, name, config, schedule_config: {} })
        setMessage('连接器实例已创建。')
      }
      await load()
      closeDrawer()
    } catch (e) {
      setDrawerError((e as Error).message)
    } finally {
      setPendingAction(null)
    }
  }

  const edit = (instance: Instance) => {
    setEditingId(instance.id)
    setDefinitionId(instance.definition_id)
    setName(instance.name)
    setConfig(instance.config)
    setMessage(null)
    setDrawerError(null)
    setDrawerOpen(true)
  }

  const action = async (id: string, actionName: 'enable' | 'disable' | 'archive') => {
    setPendingAction(`${actionName}:${id}`)
    setPageError(null)
    try {
      await api.post(`/api/v1/admin/connector-instances/${id}/${actionName}`)
      setMessage(actionName === 'archive' ? '连接器实例已归档。' : actionName === 'enable' ? '连接器实例已启用。' : '连接器实例已停用。')
      await load()
    } catch (e) {
      setPageError((e as Error).message)
    } finally {
      setPendingAction(null)
    }
  }

  const openRun = (instance: Instance, dryRun: boolean) => {
    const availableSources = sources.filter((item) => item.connector_instance_id === instance.id && item.enabled)
    const availableAccounts = accounts.filter((item) => item.connector_instance_id === instance.id && item.status === 'healthy')
    setRunInstanceId(instance.id)
    setRunSourceId(availableSources[0]?.id || '')
    setRunAccountId(availableAccounts[0]?.id || '')
    setRunLimit(5)
    setRunDry(dryRun)
    setRunError(null)
    setMessage(null)
    setRunOpen(true)
  }

  const executeRun = async () => {
    if (!runInstance) return setRunError('运行实例不存在，请关闭后刷新页面重试。')
    if (!runSourceId) return setRunError('请选择一个已启用信源。')
    if (runRequiresAccount && !runAccountId) return setRunError('该连接器运行需要平台账号。请先选择账号；如果没有可选账号，请前往“账号 / 风险”新增并配置。')
    setPendingAction(`run:${runInstance.id}`)
    setRunError(null)
    try {
      const result = await api.post<{ run_id: string; status: string }>(
        `/api/v1/admin/connector-instances/${runInstance.id}/test-runs`,
        {
          source_id: runSourceId,
          platform_account_id: runAccountId || null,
          requested_limit: runLimit,
          dry_run: runDry,
        },
      )
      setMessage(`${runDry ? '测试运行' : '立即执行'}已创建：${result.status} / ${result.run_id}`)
      setRunOpen(false)
      await load()
    } catch (e) {
      setRunError((e as Error).message)
    } finally {
      setPendingAction(null)
    }
  }

  return <div className="operations-page">
    <ErrorBanner error={pageError}/>
    {message && <div className="success-banner"><span>{message}</span>{message.includes('运行') && onNavigate && <button className="quiet-action" onClick={() => onNavigate('runs')}>查看运行记录</button>}</div>}

    <section className="panel">
      <ResourceHeader
        title="连接器实例"
        description="实例负责把一种连接器能力落到具体运行配置。运行前会显式选择信源；需要登录态的平台还必须选择同实例的平台账号。"
        actions={<><button onClick={() => void load()}>刷新</button><button className="primary" onClick={openCreate}>新建连接器实例</button></>}
      />
      {instances.length===0 ? <Empty text="暂无连接器实例" helper="先创建一个实例，再为它配置信源与采集任务。" action={<button className="primary" onClick={openCreate}>新建连接器实例</button>}/> : <div className="table-wrap"><table><thead><tr><th>实例名称</th><th>平台 / 类型</th><th>当前状态</th><th>配置版本</th><th>运行准备</th><th>操作</th></tr></thead><tbody>{instances.map((item) => {
        const definition = definitions.find((d) => d.id === item.definition_id)
        const runnableSources = sources.filter((source) => source.connector_instance_id === item.id && source.enabled)
        const usableAccounts = accounts.filter((account) => account.connector_instance_id === item.id && account.status === 'healthy')
        const requiresAccount = Boolean(definition?.capabilities.requires_account)
        return <tr key={item.id}>
          <td><strong>{item.name}</strong><small className="technical-meta">ID · {item.id}</small></td>
          <td>{definition ? `${definition.display_name} · ${definition.platform}` : '未知连接器'}</td>
          <td>{item.enabled ? enabledLabel(true) : (sourceStatusLabel[item.status] || enabledLabel(false))}</td>
          <td>v{item.config_version}</td>
          <td><div className="status-stack"><span>{runnableSources.length > 0 ? `${runnableSources.length} 个已启用信源` : '暂无可运行信源'}</span><small>{requiresAccount ? (usableAccounts.length > 0 ? `${usableAccounts.length} 个健康平台账号` : '需要平台账号，当前未配置') : '该连接器无需平台账号'}</small></div></td>
          <td><div className="actions action-cell">
            <button className="primary" disabled={Boolean(pendingAction)||runnableSources.length===0} title={runnableSources.length===0?'请先创建并启用信源':'选择信源与运行账号后执行'} onClick={() => openRun(item, false)}>立即执行</button>
            <button disabled={Boolean(pendingAction)||runnableSources.length===0} title={runnableSources.length===0?'请先创建并启用信源':'选择信源与运行账号后进行少量测试'} onClick={() => openRun(item, true)}>测试运行</button>
            <button disabled={Boolean(pendingAction)} onClick={() => edit(item)}>编辑</button>
            <details className="more-actions"><summary>更多</summary><button disabled={Boolean(pendingAction)} onClick={() => void action(item.id, item.enabled ? 'disable' : 'enable')}>{pendingAction === `${item.enabled ? 'disable' : 'enable'}:${item.id}` ? '正在处理…' : item.enabled ? '停用' : '启用'}</button><button className="danger" disabled={Boolean(pendingAction)} onClick={() => { if (window.confirm('归档连接器实例？已关联的历史记录不会删除。')) void action(item.id, 'archive') }}>{pendingAction === `archive:${item.id}` ? '正在归档…' : '归档'}</button></details>
          </div>{requiresAccount&&usableAccounts.length===0&&<small className="field-helper">运行前需要平台账号。{onNavigate&&<button className="inline-link" onClick={() => onNavigate('risk')}>去配置账号</button>}</small>}</td>
        </tr>
      })}</tbody></table></div>}
    </section>

    <Drawer open={drawerOpen} title={editingId ? '编辑连接器实例' : '新建连接器实例'} description="先选择连接器类型和名称，再配置该实例允许的采集能力与运行参数。" width="wide" onClose={closeDrawer} footer={<><button disabled={pendingAction==='save'} onClick={closeDrawer}>取消</button><button className="primary" disabled={pendingAction==='save'} onClick={() => void save()}>{pendingAction==='save'?'正在保存…':editingId?'保存修改':'创建实例'}</button></>}>
      <ErrorBanner error={drawerError}/>
      <div className="drawer-section"><h3>基本信息</h3><p>选择实例所属连接器，并用一个易识别的名称区分不同采集配置。</p><div className="form-grid"><label className="field-full">连接器类型<select disabled={Boolean(editingId)} value={definitionId} onChange={(event) => { setDefinitionId(event.target.value); setConfig({}); setDrawerError(null) }}><option value="">请选择</option>{definitions.map((definition) => <option key={definition.id} value={definition.id}>{definition.display_name} · {definition.platform}</option>)}</select></label><label className="field-full">实例名称<input aria-label="实例名称" value={name} onChange={(event) => { setName(event.target.value); setDrawerError(null) }} placeholder="例如：B站热点采集"/></label></div></div>
      {selected && <div className="drawer-section"><h3>采集与运行配置</h3><p>按连接器能力配置采集模式、运行参数和附加选项。</p><SchemaForm schema={selected.config_schema} uiSchema={selected.ui_schema} value={config} onChange={(next) => { setConfig(next); setDrawerError(null) }}/></div>}
    </Drawer>

    <Drawer open={runOpen} title={runDry ? '测试运行' : '立即执行采集'} description={runDry ? '测试运行会执行真实采集请求，但 dry-run 不写入原始信号；运行前仍必须通过账号、预算与风险预检。' : '执行一次受控采集。请明确选择信源和平台账号，避免后台默默使用错误账号。'} onClose={() => setRunOpen(false)} footer={<><button disabled={pendingAction?.startsWith('run:')} onClick={() => setRunOpen(false)}>取消</button><button className="primary" disabled={Boolean(pendingAction)||!runSourceId||(runRequiresAccount&&!runAccountId)} onClick={() => void executeRun()}>{pendingAction?.startsWith('run:')?'正在创建运行…':runDry?'开始测试运行':'开始执行'}</button></>}>
      <ErrorBanner error={runError}/>
      <div className="drawer-section"><h3>运行对象</h3><p>{runInstance?.name || '当前实例'} · {runDefinition?.display_name || runInstance?.platform || ''}</p><div className="form-grid"><label className="field-full">信源<select value={runSourceId} onChange={(event) => { setRunSourceId(event.target.value); setRunError(null) }}><option value="">请选择已启用信源</option>{runSources.map((source) => <option key={source.id} value={source.id}>{source.name} · {source.mode}</option>)}</select></label><label>单次采集上限<input type="number" min="1" max="100" value={runLimit} onChange={(event) => setRunLimit(Math.max(1, Math.min(100, Number(event.target.value) || 1)))}/></label></div></div>
      <div className="drawer-section"><h3>运行账号</h3><p>{runRequiresAccount ? '该连接器定义要求平台账号，CollectorRuntime 预检会验证账号必须属于当前实例且处于可运行状态。' : '该连接器不强制账号；如有业务需要仍可显式选择一个同实例账号。'}</p><div className="form-grid"><label className="field-full">平台账号<select value={runAccountId} onChange={(event) => { setRunAccountId(event.target.value); setRunError(null) }}><option value="">{runRequiresAccount?'请选择平台账号':'不使用平台账号'}</option>{runAccounts.map((account) => <option key={account.id} value={account.id}>{account.display_name} · {account.account_identifier}</option>)}</select></label></div>{runRequiresAccount&&runAccounts.length===0&&<div className="prerequisite-hint"><span>当前实例没有健康的平台账号，无法通过运行预检。</span>{onNavigate&&<button className="quiet-action" onClick={() => { setRunOpen(false); onNavigate('risk') }}>去账号 / 风险配置</button>}</div>}</div>
    </Drawer>
  </div>
}
