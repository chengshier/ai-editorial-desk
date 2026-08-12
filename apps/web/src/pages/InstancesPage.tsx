import { useCallback, useEffect, useMemo, useState } from 'react'
import { AdminApi } from '../api'
import { Empty, ErrorBanner, Panel } from '../components/common'
import { enabledLabel, sourceStatusLabel } from '../uiLabels'
import { SchemaForm, validateSchemaValue } from '../components/SchemaForm'
import type { Definition, Instance, Source } from '../types'

export function InstancesPage({ api }: { api: AdminApi }) {
  const [instances, setInstances] = useState<Instance[]>([])
  const [definitions, setDefinitions] = useState<Definition[]>([])
  const [sources, setSources] = useState<Source[]>([])
  const [definitionId, setDefinitionId] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [config, setConfig] = useState<Record<string, unknown>>({})
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
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
  }

  const save = async () => {
    if (!selected || !name.trim()) return setError('请选择连接器类型并填写实例名称')
    if (Object.keys(validateSchemaValue(selected.config_schema, config)).length) {
      return setError('配置未通过表单校验')
    }
    try {
      if (editingId) {
        await api.patch(`/api/v1/admin/connector-instances/${editingId}`, { name, config })
        setMessage('实例配置已更新；后端 JSON Schema 校验仍是最终权威。')
      } else {
        await api.post('/api/v1/admin/connector-instances', {
          definition_id: selected.id,
          name,
          config,
          schedule_config: {},
        })
        setMessage('实例已创建。')
      }
      resetForm()
      await load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const edit = (instance: Instance) => {
    setEditingId(instance.id)
    setDefinitionId(instance.definition_id)
    setName(instance.name)
    setConfig(instance.config)
    setMessage(null)
    setError(null)
  }

  const action = async (id: string, actionName: 'enable' | 'disable' | 'archive') => {
    try {
      await api.post(`/api/v1/admin/connector-instances/${id}/${actionName}`)
      await load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const run = async (instance: Instance, dryRun: boolean) => {
    const source = sources.find((item) => item.connector_instance_id === instance.id && item.enabled)
    if (!source) return setError('该实例没有可运行的已启用信源')
    try {
      const result = await api.post<{ run_id: string; status: string }>(
        `/api/v1/admin/connector-instances/${instance.id}/test-runs`,
        { source_id: source.id, requested_limit: 5, dry_run: dryRun },
      )
      setMessage(`${dryRun ? '测试运行' : '立即执行'}已完成：${result.status} / ${result.run_id}`)
      await load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return <>
    <Panel title={editingId ? '编辑连接器实例' : '新建连接器实例'} actions={editingId ? <button onClick={resetForm}>取消编辑</button> : undefined}>
      <div className="page-intro"><p>管理各平台连接器的采集配置与运行方式。</p></div>
      <ErrorBanner error={error}/>
      {message && <p className="notice">{message}</p>}
      <div className="form-grid operations-form">
        <label className="field-md">连接器类型<select disabled={Boolean(editingId)} value={definitionId} onChange={(event) => { setDefinitionId(event.target.value); setConfig({}) }}><option value="">请选择</option>{definitions.map((definition) => <option key={definition.id} value={definition.id}>{definition.display_name} · {definition.platform}</option>)}</select></label>
        <label className="field-md">实例名称<input value={name} onChange={(event) => setName(event.target.value)}/></label>
      </div>
      {selected && <><h3 className="section-title">采集配置</h3><SchemaForm schema={selected.config_schema} uiSchema={selected.ui_schema} value={config} onChange={setConfig}/></>}<button className="primary" onClick={save}>{editingId ? '保存修改' : '新建连接器实例'}</button>
    </Panel>
    <Panel title="实例列表" actions={<button onClick={load}>刷新</button>}>{instances.length===0?<Empty text="暂无连接器实例"/>:<div className="table-wrap"><table><thead><tr><th>实例名称</th><th>平台 / 类型</th><th>当前状态</th><th>配置版本</th><th>操作</th></tr></thead><tbody>{instances.map((item) => {const definition=definitions.find(d=>d.id===item.definition_id);return <tr key={item.id}><td>{item.name}</td><td>{definition?`${definition.platform} · ${definition.display_name}`:'未知连接器'}</td><td>{item.enabled?enabledLabel(true):(sourceStatusLabel[item.status]||enabledLabel(false))}</td><td>v{item.config_version}</td><td className="actions"><button onClick={() => edit(item)}>编辑</button><button onClick={() => void run(item, true)} title="使用少量数据进行无副作用验证">测试运行</button><button className="primary" onClick={() => void run(item, false)} title="使用当前配置立即创建一次真实运行">立即执行</button><details className="more-actions"><summary>更多</summary><button onClick={() => void action(item.id, item.enabled ? 'disable' : 'enable')}>{item.enabled ? '停用' : '启用'}</button><button className="danger" onClick={() => void action(item.id, 'archive')}>归档</button></details></td></tr>})}</tbody></table></div>}</Panel>
  </>
}
