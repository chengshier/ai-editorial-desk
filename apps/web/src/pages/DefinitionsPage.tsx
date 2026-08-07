import { useEffect, useState } from 'react'
import { AdminApi } from '../api'
import { Empty, ErrorBanner, JsonView, Panel } from '../components/common'
import { StateBadge } from '../components/StateBadge'
import type { Definition } from '../types'

export function DefinitionsPage({ api }: { api: AdminApi }) {
  const [items, setItems] = useState<Definition[]>([])
  const [selected, setSelected] = useState<Definition | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = () => api.page<Definition>('/api/v1/admin/connector-definitions?page_size=100')
    .then((page) => setItems(page.items)).catch((e: Error) => setError(e.message))
  useEffect(() => { void load() }, [])
  return <Panel title="Connector Definitions" actions={<button onClick={load}>刷新</button>}>
    <ErrorBanner error={error} />
    {!items.length ? <Empty /> : <div className="split"><div className="table-wrap"><table><thead><tr><th>名称</th><th>类型 / 平台</th><th>状态</th><th>版本</th></tr></thead><tbody>
      {items.map((item) => <tr key={item.id} onClick={() => setSelected(item)}>
        <td>{item.display_name}</td><td>{item.connector_type} / {item.platform}</td>
        <td className="badges"><StateBadge ok={item.registered} label="注册"/><StateBadge ok={item.implemented} label="实现"/><StateBadge ok={item.enabled} label="启用"/><StateBadge ok={item.validated} label="验真"/></td>
        <td>{item.implementation_version}</td>
      </tr>)}
    </tbody></table></div>{selected && <aside><h3>{selected.display_name}</h3><p>Capabilities</p><JsonView value={selected.capabilities}/><p>Config Schema</p><JsonView value={selected.config_schema}/></aside>}</div>}
  </Panel>
}
