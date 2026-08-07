import { useCallback, useEffect, useMemo, useState } from 'react'
import { AdminApi } from '../api'
import { ErrorBanner, Panel } from '../components/common'
import { SchemaForm, validateSchemaValue } from '../components/SchemaForm'
import type { Definition, Instance } from '../types'

export function InstancesPage({ api }: { api: AdminApi }) {
  const [instances, setInstances] = useState<Instance[]>([])
  const [definitions, setDefinitions] = useState<Definition[]>([])
  const [definitionId, setDefinitionId] = useState('')
  const [name, setName] = useState('')
  const [config, setConfig] = useState<Record<string, unknown>>({})
  const [error, setError] = useState<string | null>(null)
  const selected = useMemo(
    () => definitions.find((item) => item.id === definitionId),
    [definitions, definitionId],
  )

  const load = useCallback(async () => {
    try {
      const [instancePage, definitionPage] = await Promise.all([
        api.page<Instance>('/api/v1/admin/connector-instances?page_size=100'),
        api.page<Definition>('/api/v1/admin/connector-definitions?page_size=100'),
      ])
      setInstances(instancePage.items)
      setDefinitions(definitionPage.items)
      if (definitionPage.items[0]) {
        setDefinitionId((current) => current || definitionPage.items[0].id)
      }
    } catch (e) {
      setError((e as Error).message)
    }
  }, [api])

  useEffect(() => {
    void load()
  }, [load])

  const create = async () => {
    if (!selected || !name.trim()) return setError('请选择 Definition 并填写实例名称')
    if (Object.keys(validateSchemaValue(selected.config_schema, config)).length) {
      return setError('配置未通过表单校验')
    }
    try {
      await api.post('/api/v1/admin/connector-instances', {
        definition_id: selected.id,
        name,
        config,
        schedule_config: {},
      })
      setName('')
      setConfig({})
      await load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const action = async (id: string, actionName: 'enable' | 'disable' | 'archive') => {
    try {
      await api.post(`/api/v1/admin/connector-instances/${id}/${actionName}`)
      await load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return <>
    <Panel title="Connector Instances" actions={<button onClick={load}>刷新</button>}>
      <ErrorBanner error={error}/>
      <div className="form-grid">
        <label>Definition<select value={definitionId} onChange={(event) => { setDefinitionId(event.target.value); setConfig({}) }}><option value="">请选择</option>{definitions.map((definition) => <option key={definition.id} value={definition.id}>{definition.display_name}</option>)}</select></label>
        <label>实例名称<input value={name} onChange={(event) => setName(event.target.value)}/></label>
      </div>
      {selected && <SchemaForm schema={selected.config_schema} uiSchema={selected.ui_schema} value={config} onChange={setConfig}/>}<button onClick={create}>新建实例</button>
    </Panel>
    <Panel title="实例列表"><div className="table-wrap"><table><thead><tr><th>名称</th><th>状态</th><th>版本</th><th>操作</th></tr></thead><tbody>{instances.map((item) => <tr key={item.id}><td>{item.name}</td><td>{item.status} / {item.enabled ? '启用' : '停用'}</td><td>config v{item.config_version}</td><td className="actions"><button onClick={() => void action(item.id, item.enabled ? 'disable' : 'enable')}>{item.enabled ? '停用' : '启用'}</button><button className="danger" onClick={() => void action(item.id, 'archive')}>归档</button></td></tr>)}</tbody></table></div></Panel>
  </>
}
