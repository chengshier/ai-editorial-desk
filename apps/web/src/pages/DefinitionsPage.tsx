import { useCallback, useEffect, useState } from 'react'
import { AdminApi } from '../api'
import { Empty, ErrorBanner, JsonView, Panel } from '../components/common'
import { StateBadge } from '../components/StateBadge'
import type { Definition } from '../types'

export function DefinitionsPage({ api }: { api: AdminApi }) {
  const [items, setItems] = useState<Definition[]>([])
  const [selected, setSelected] = useState<Definition | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const page = await api.page<Definition>('/api/v1/admin/connector-definitions?page_size=100')
      setItems(page.items)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [api])

  useEffect(() => {
    void load()
  }, [load])

  return <Panel title="连接器定义" actions={<button onClick={load}>刷新</button>}>
    <div className="page-intro"><p>查看系统已注册的数据源连接器及其能力支持情况。</p><span className="readonly-note">只读配置</span></div>
    <ErrorBanner error={error} />
    {!items.length ? <Empty text="暂无已注册的连接器定义" /> : <div className="split"><div className="table-wrap"><table><thead><tr><th>名称</th><th>平台 / 实现方式</th><th>支持状态</th><th>版本</th></tr></thead><tbody>
      {items.map((item) => <tr key={item.id} onClick={() => setSelected(item)}>
        <td>{item.display_name}</td><td>{item.connector_type} / {item.platform}</td>
        <td className="badges"><StateBadge ok={item.registered} label="注册"/><StateBadge ok={item.implemented} label="实现"/><StateBadge ok={item.enabled} label="启用"/><StateBadge ok={item.validated} label="验真"/></td>
        <td>{item.implementation_version}</td>
      </tr>)}
    </tbody></table></div>{selected && <aside><h3>{selected.display_name}</h3><p>能力支持（技术详情）</p><JsonView value={selected.capabilities}/><p>配置结构（技术详情）</p><JsonView value={selected.config_schema}/></aside>}</div>}
  </Panel>
}
