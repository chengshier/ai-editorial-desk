import { useCallback, useEffect, useState } from 'react'
import { AdminApi } from '../api'
import { Empty, ErrorBanner, JsonView, Panel } from '../components/common'
import { StateBadge } from '../components/StateBadge'
import { capabilityLabel } from '../uiLabels'
import type { Definition } from '../types'

function capabilityModes(item: Definition): string[] {
  const declared = item.capabilities.allowed_modes
  if (Array.isArray(declared)) return declared.filter((mode): mode is string => typeof mode === 'string')
  return ['search', 'account', 'detail', 'comments', 'feed', 'hotlist', 'manual_import'].filter((mode) => item.capabilities[mode] === true)
}

export function DefinitionsPage({ api }: { api: AdminApi }) {
  const [items, setItems] = useState<Definition[]>([])
  const [selected, setSelected] = useState<Definition | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const page = await api.page<Definition>('/api/v1/admin/connector-definitions?page_size=100')
      setItems(page.items)
      setSelected((current) => current ? page.items.find((item) => item.id === current.id) || null : null)
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [api])

  useEffect(() => {
    void load()
  }, [load])

  return <Panel title="连接器能力目录" actions={<button onClick={load}>刷新</button>}>
    <div className="page-intro"><div><p>这里展示系统代码已经注册的数据连接能力，不是业务 CRUD 配置页。需要实际采集时，请先创建连接器实例，再创建具体信源。</p><small className="muted-text">状态说明：已注册 = 系统已识别；已实现 = 当前代码存在可运行实现；已启用 = Runtime 允许使用；已验真 = 最近有效验证通过。</small></div><span className="readonly-note">系统只读</span></div>
    <ErrorBanner error={error} />
    {!items.length ? <Empty text="暂无已注册的连接器定义" /> : <div className="split"><div className="table-wrap"><table><thead><tr><th>连接器</th><th>支持能力</th><th>运行要求</th><th>状态</th><th>版本</th></tr></thead><tbody>
      {items.map((item) => {
        const modes = capabilityModes(item)
        const requiresAccount = item.capabilities.requires_account === true
        return <tr key={item.id} onClick={() => setSelected(item)}>
          <td><strong>{item.display_name}</strong><small className="technical-meta">{item.platform} · {item.connector_type}</small></td>
          <td><div className="badges">{modes.length ? modes.map((mode) => <span className="badge wb-info" key={mode}>{capabilityLabel[mode] || mode}</span>) : <span className="muted-text">暂无声明</span>}</div></td>
          <td>{requiresAccount ? '需要平台账号' : '无需平台账号'}<small className="technical-meta">{item.capabilities.supports_checkpoint === true ? '支持增量检查点' : '无增量检查点'}</small></td>
          <td className="badges"><StateBadge ok={item.registered} label="注册"/><StateBadge ok={item.implemented} label="实现"/><StateBadge ok={item.enabled} label="启用"/><StateBadge ok={item.validated} label="验真"/></td>
          <td>{item.implementation_version}</td>
        </tr>
      })}
    </tbody></table></div>{selected && <aside><h3>{selected.display_name}</h3><p>{selected.platform} · {selected.connector_type}</p><div className="status-stack"><strong>可运行状态</strong><span>{selected.registered && selected.implemented && selected.enabled ? '已具备主系统运行条件' : '当前不可直接运行'}</span><small>{selected.validated ? '最近有效验证：通过' : '最近有效验证：尚未通过或未执行'}</small></div><h4>能力</h4><div className="badges">{capabilityModes(selected).map((mode) => <span className="badge wb-info" key={mode}>{capabilityLabel[mode] || mode}</span>)}</div><p>{selected.capabilities.requires_account === true ? '运行时必须选择属于同一实例的健康平台账号。' : '运行时不强制平台账号。'}</p><p>{selected.capabilities.supports_checkpoint === true ? '支持按信源维护增量检查点。' : '该连接器不维护增量检查点。'}</p><details><summary>开发者技术详情</summary><h4>能力原始定义</h4><JsonView value={selected.capabilities}/><h4>实例配置结构</h4><JsonView value={selected.config_schema}/></details></aside>}</div>}
  </Panel>
}