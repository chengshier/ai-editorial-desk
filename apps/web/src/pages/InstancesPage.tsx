import { useCallback, useEffect, useMemo, useState } from 'react'
import { AdminApi } from '../api'
import { Drawer, Empty, ErrorBanner, ResourceHeader } from '../components/common'
import { enabledLabel, sourceStatusLabel } from '../uiLabels'
import { SchemaForm, validateSchemaValue } from '../components/SchemaForm'
import type { Definition, Instance, Source } from '../types'

export function InstancesPage({ api, onNavigate }: { api: AdminApi; onNavigate?: (page: 'runs') => void }) {
  const [instances, setInstances] = useState<Instance[]>([])
  const [definitions, setDefinitions] = useState<Definition[]>([])
  const [sources, setSources] = useState<Source[]>([])
  const [definitionId, setDefinitionId] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [config, setConfig] = useState<Record<string, unknown>>({})
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<string | null>(null)
  const selected = useMemo(
    () => definitions.find((item) => item.id === definitionId),
    [definitions, definitionId],
  )

  const load = useCallback(async () => {
    try {
      const [instancePage, definitionPage, sourcePage] = await Promise.all([
        api.page<Instance>('/api/v1/admin/connector-instances?page_size=100'),
        api.page<Definition>('/api/v1/admin/connector-definitions?page_size=100'),
        api.page<Source>('/api/v1/admin/sources?page_size=100'),
      ])
      setInstances(instancePage.items)
      setDefinitions(definitionPage.items)
      setSources(sourcePage.items)
      if (definitionPage.items[0]) {
        setDefinitionId((current) => current || definitionPage.items[0].id)
      }
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [api])

  useEffect(() => {
    void load()
  }, [load])

  const resetForm = () => {
    setEditingId(null)
    setName('')
    setConfig({})
    if (definitions[0]) setDefinitionId(definitions[0].id)
  }

  const openCreate = () => {
    resetForm()
    setMessage(null)
    setError(null)
    setDrawerOpen(true)
  }

  const save = async () => {
    if (!selected || !name.trim()) return setError('请选择连接器类型并填写实例名称')
    if (Object.keys(validateSchemaValue(selected.config_schema, config, selected.ui_schema)).length) {
      return setError('配置未通过表单校验，请检查必填项与字段范围')
    }
    setPendingAction('save')
    setError(null)
    try {
      if (editingId) {
        await api.patch(`/api/v1/admin/connector-instances/${editingId}`, { name, config })
        setMessage('连接器实例已更新。')
      } else {
        await api.post('/api/v1/admin/connector-instances', {
          definition_id: selected.id,
          name,
          config,
          schedule_config: {},
        })
        setMessage('连接器实例已创建。')
      }
      await load()
      setDrawerOpen(false)
      resetForm()
    } catch (e) {
      setError((e as Error).message)
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
    setError(null)
    setDrawerOpen(true)
  }

  const action = async (id: string, actionName: 'enable' | 'disable' | 'archive') => {
    setPendingAction(`${actionName}:${id}`)
    setError(null)
    try {
      await api.post(`/api/v1/admin/connector-instances/${id}/${actionName}`)
      setMessage(actionName === 'archive' ? '连接器实例已归档。' : actionName === 'enable' ? '连接器实例已启用。' : '连接器实例已停用。')
      await load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPendingAction(null)
    }
  }

  const run = async (instance: Instance, dryRun: boolean) => {
    const source = sources.find((item) => item.connector_instance_id === instance.id && item.enabled)
    if (!source) return setError('该实例没有已启用的信源。请先在“信源”页面创建或启用信源。')
    setPendingAction(`run:${instance.id}`)
    setError(null)
    try {
      const result = await api.post<{ run_id: string; status: string }>(
        `/api/v1/admin/connector-instances/${instance.id}/test-runs`,
        { source_id: source.id, requested_limit: 5, dry_run: dryRun },
      )
      setMessage(`${dryRun ? '运行已创建' : '立即执行已创建'}：${result.status} / ${result.run_id}`)
      await load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPendingAction(null)
    }
  }

  return <div className="operations-page">
    <ErrorBanner error={error}/>
    {message && <div className="success-banner"><span>{message}</span>{message.includes('运行') && onNavigate && <button className="quiet-action" onClick={() => onNavigate('runs')}>查看运行记录</button>}</div>}

    <section className="panel">
      <ResourceHeader
        title="连接器实例"
        description="实例负责把一种连接器能力落到具体运行配置。日常先管理列表，需要新增或修改时再进入配置流程。"
        actions={<><button onClick={() => void load()}>刷新</button><button className="primary" onClick={openCreate}>新建连接器实例</button></>}
      />
      {instances.length===0 ? <Empty text="暂无连接器实例" helper="先创建一个实例，再为它配置信源与采集任务。" action={<button className="primary" onClick={openCreate}>新建连接器实例</button>}/> : <div className="table-wrap"><table><thead><tr><th>实例名称</th><th>平台 / 类型</th><th>当前状态</th><th>配置版本</th><th>可运行信源</th><th>操作</th></tr></thead><tbody>{instances.map((item) => {
        const definition=definitions.find((d)=>d.id===item.definition_id)
        const runnableSources=sources.filter((source)=>source.connector_instance_id===item.id&&source.enabled)
        const running=pendingAction===`run:${item.id}`
        return <tr key={item.id}>
          <td><strong>{item.name}</strong><small className="technical-meta">ID · {item.id}</small></td>
          <td>{definition?`${definition.display_name} · ${definition.platform}`:'未知连接器'}</td>
          <td>{item.enabled?enabledLabel(true):(sourceStatusLabel[item.status]||enabledLabel(false))}</td>
          <td>v{item.config_version}</td>
          <td>{runnableSources.length>0?`${runnableSources.length} 个已启用`:'暂无'}</td>
          <td><div className="actions action-cell">
            <button className="primary" disabled={Boolean(pendingAction)||runnableSources.length===0} title={runnableSources.length===0?'请先创建并启用信源':'按当前配置创建一次真实运行'} onClick={() => void run(item, false)}>{running?'正在创建…':'立即执行'}</button>
            <button disabled={Boolean(pendingAction)||runnableSources.length===0} title={runnableSources.length===0?'请先创建并启用信源':'使用少量数据进行测试运行'} onClick={() => void run(item, true)}>测试运行</button>
            <button disabled={Boolean(pendingAction)} onClick={() => edit(item)}>编辑</button>
            <details className="more-actions"><summary>更多</summary><button disabled={Boolean(pendingAction)} onClick={() => void action(item.id, item.enabled ? 'disable' : 'enable')}>{pendingAction === `${item.enabled ? 'disable' : 'enable'}:${item.id}` ? '正在处理…' : item.enabled ? '停用' : '启用'}</button><button className="danger" disabled={Boolean(pendingAction)} onClick={() => { if (window.confirm('归档连接器实例？已关联的历史记录不会删除。')) void action(item.id, 'archive') }}>{pendingAction === `archive:${item.id}` ? '正在归档…' : '归档'}</button></details>
          </div>{runnableSources.length===0&&<small className="field-helper">先配置并启用信源后才能运行。</small>}</td>
        </tr>
      })}</tbody></table></div>}
    </section>

    <Drawer
      open={drawerOpen}
      title={editingId ? '编辑连接器实例' : '新建连接器实例'}
      description="先选择连接器类型和名称，再配置该实例允许的采集能力与运行参数。"
      width="wide"
      onClose={() => { setDrawerOpen(false); resetForm() }}
      footer={<><button disabled={pendingAction==='save'} onClick={() => { setDrawerOpen(false); resetForm() }}>取消</button><button className="primary" disabled={pendingAction==='save'} onClick={() => void save()}>{pendingAction==='save'?'正在保存…':editingId?'保存修改':'创建实例'}</button></>}
    >
      <div className="drawer-section"><h3>基本信息</h3><p>选择实例所属连接器，并用一个易识别的名称区分不同采集配置。</p><div className="form-grid"><label className="field-full">连接器类型<select disabled={Boolean(editingId)} value={definitionId} onChange={(event) => { setDefinitionId(event.target.value); setConfig({}) }}><option value="">请选择</option>{definitions.map((definition) => <option key={definition.id} value={definition.id}>{definition.display_name} · {definition.platform}</option>)}</select></label><label className="field-full">实例名称<input aria-label="实例名称" value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：B站热点采集"/></label></div></div>
      {selected && <div className="drawer-section"><h3>采集与运行配置</h3><p>按连接器能力配置采集模式、运行参数和附加选项。</p><SchemaForm schema={selected.config_schema} uiSchema={selected.ui_schema} value={config} onChange={setConfig}/></div>}
    </Drawer>
  </div>
}
