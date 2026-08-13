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
  const [message, setMessage] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

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

  const toggleRuntime = async (item: Definition) => {
    setPending(true)
    setError(null)
    setMessage(null)
    try {
      const updated = await api.post<Definition>(`/api/v1/admin/connector-definitions/${item.id}/${item.enabled ? 'disable' : 'enable'}`)
      setMessage(updated.enabled ? '连接器定义已启用，Runtime 可以继续使用该能力。' : '连接器定义已停用；代码能力仍保留，但 Runtime 不再允许使用。')
      await load()
      setSelected(updated)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPending(false)
    }
  }

  return <Panel title="连接器能力目录" actions={<button onClick={load}>刷新</button>}>
    <div className="page-intro"><div><p>这里展示系统代码已经注册的数据连接能力。能力、Schema 和实现版本由代码 Manifest 管理；“运行启用”是运维开关，可以在这里人工切换。</p><small className="muted-text">状态说明：已注册 = 系统已识别；已实现 = 当前代码存在可运行实现；已启用 = Runtime 允许运行；已验真 = 最近有效真实验证通过。注册、实现和验真不能在此手工伪造。</small></div><span className="readonly-note">能力定义只读 · 运行开关可操作</span></div>
    <ErrorBanner error={error} />
    {message&&<div className="success-banner">{message}</div>}
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
    </tbody></table></div>{selected && <aside><h3>{selected.display_name}</h3><p>{selected.platform} · {selected.connector_type}</p><div className="status-stack"><strong>可运行状态</strong><span>{selected.registered && selected.implemented && selected.enabled ? '已具备主系统运行条件' : '当前不可直接运行'}</span><small>{selected.validated ? '最近有效验证：通过' : '最近有效验证：尚未通过或未执行'}</small></div><div className="action-box"><strong>运行启用开关</strong><p>这里只改变数据库中的运维开关，不修改代码 Manifest、能力声明或验真结果。</p><button className={selected.enabled ? 'danger' : 'primary'} disabled={pending} onClick={() => void toggleRuntime(selected)}>{pending?'正在处理…':selected.enabled?'停用此连接器':'启用此连接器'}</button></div><h4>能力</h4><div className="badges">{capabilityModes(selected).map((mode) => <span className="badge wb-info" key={mode}>{capabilityLabel[mode] || mode}</span>)}</div><p>{selected.capabilities.requires_account === true ? '运行时必须选择属于同一实例的健康平台账号。' : '运行时不强制平台账号。'}</p><p>{selected.capabilities.supports_checkpoint === true ? '支持按信源维护增量检查点。' : '该连接器不维护增量检查点。'}</p><details><summary>开发者技术详情</summary><h4>能力原始定义</h4><JsonView value={selected.capabilities}/><h4>实例配置结构</h4><JsonView value={selected.config_schema}/></details></aside>}</div>}
  </Panel>
}