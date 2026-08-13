import { useCallback, useEffect, useState } from 'react'
import { AdminApi } from '../api'
import { Empty, ErrorBanner, Panel } from '../components/common'
import { enabledLabel, sourceModeLabel, sourceStatusLabel } from '../uiLabels'
import type { Instance, Source } from '../types'

export function SourcesPage({ api, onNavigate }: { api: AdminApi; onNavigate?: (page: 'runs') => void }) {
  const [sources, setSources] = useState<Source[]>([])
  const [instances, setInstances] = useState<Instance[]>([])
  const [editingId, setEditingId] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [form, setForm] = useState({
    connector_instance_id: '',
    name: '',
    source_type: 'rss',
    mode: 'feed',
    scope_key: '',
    external_ref: '',
  })
  const [error, setError] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [sourcePage, instancePage] = await Promise.all([
        api.page<Source>('/api/v1/admin/sources?page_size=100'),
        api.page<Instance>('/api/v1/admin/connector-instances?page_size=100'),
      ])
      setSources(sourcePage.items)
      setInstances(instancePage.items)
      if (instancePage.items[0]) {
        setForm((current) => current.connector_instance_id
          ? current
          : { ...current, connector_instance_id: instancePage.items[0].id })
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
    setForm((current) => ({ ...current, name: '', scope_key: '', external_ref: '' }))
  }

  const save = async () => {
    setPendingAction('save')
    setError(null)
    try {
      if (editingId) {
        await api.patch(`/api/v1/admin/sources/${editingId}`, {
          name: form.name,
          external_ref: form.external_ref || null,
        })
        setMessage('信源已更新。')
      } else {
        await api.post('/api/v1/admin/sources', {
          ...form,
          external_ref: form.external_ref || null,
          config: {},
          enabled: true,
        })
        setMessage('信源已创建。')
      }
      resetForm()
      await load()
    } catch (e) {
      setError((e as Error).message)
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
    setError(null)
  }

  const toggle = async (source: Source) => {
    setPendingAction(`toggle:${source.id}`)
    setError(null)
    try {
      await api.patch(`/api/v1/admin/sources/${source.id}`, { enabled: !source.enabled })
      setMessage(source.enabled ? '信源已停用。' : '信源已启用。')
      await load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPendingAction(null)
    }
  }

  const archive = async (source: Source) => {
    if (!window.confirm('归档信源？历史原始信号不会删除。')) return
    setPendingAction(`archive:${source.id}`)
    setError(null)
    try {
      await api.post(`/api/v1/admin/sources/${source.id}/archive`)
      setMessage('信源已归档。')
      await load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPendingAction(null)
    }
  }

  const testRun = async (source: Source) => {
    setPendingAction(`run:${source.id}`)
    setError(null)
    try {
      const result = await api.post<{ run_id: string; status: string }>(
        `/api/v1/admin/connector-instances/${source.connector_instance_id}/test-runs`,
        { source_id: source.id, requested_limit: 5, dry_run: true },
      )
      setMessage(`测试运行已创建：${result.status} / ${result.run_id}`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPendingAction(null)
    }
  }

  return <>
    <Panel title={editingId ? '编辑信源' : '新建信源'} actions={editingId ? <button onClick={resetForm}>取消编辑</button> : undefined}>
      <div className="page-intro"><p>管理用于采集和编辑判断的数据来源。</p></div>
      <ErrorBanner error={error}/>{message && <p className="notice">{message}{onNavigate && <button className="quiet-action" onClick={() => onNavigate('runs')}>查看运行记录</button>}</p>}<div className="form-grid operations-form">
      <label className="field-md">所属实例<select disabled={Boolean(editingId)} value={form.connector_instance_id} onChange={(event) => setForm({ ...form, connector_instance_id: event.target.value })}>{instances.map((instance) => <option key={instance.id} value={instance.id}>{instance.name}</option>)}</select></label>
      <label className="field-md">信源名称<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })}/></label><label className="field-sm">来源类型<input disabled={Boolean(editingId)} value={form.source_type} onChange={(event) => setForm({ ...form, source_type: event.target.value })}/></label><label className="field-md">采集模式<select disabled={Boolean(editingId)} value={form.mode} onChange={(event) => setForm({ ...form, mode: event.target.value })}>{Object.entries(sourceModeLabel).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><label className="field-md">作用范围<input disabled={Boolean(editingId)} value={form.scope_key} onChange={(event) => setForm({ ...form, scope_key: event.target.value })}/></label><label className="field-lg">外部引用<input value={form.external_ref} onChange={(event) => setForm({ ...form, external_ref: event.target.value })}/></label>
    </div><button className="primary" disabled={pendingAction === 'save'} onClick={save}>{pendingAction === 'save' ? '正在保存…' : editingId ? '保存修改' : '新建信源'}</button></Panel>
    <Panel title="信源列表" actions={<button onClick={load}>刷新</button>}>{sources.length===0?<Empty text="暂无信源"/>:<div className="table-wrap"><table><thead><tr><th>名称</th><th>来源类型</th><th>采集模式</th><th>状态</th><th>操作</th></tr></thead><tbody>{sources.map((source) => <tr key={source.id}><td><strong>{source.name}</strong><small className="technical-meta">{source.scope_key}</small></td><td>{source.source_type}</td><td>{sourceModeLabel[source.mode]||source.mode}</td><td>{source.enabled?enabledLabel(true):(sourceStatusLabel[source.status]||enabledLabel(false))}</td><td className="actions"><button disabled={Boolean(pendingAction)} onClick={() => edit(source)}>编辑</button><button disabled={Boolean(pendingAction)} onClick={() => void testRun(source)}>{pendingAction === `run:${source.id}` ? '正在创建…' : '测试运行'}</button><details className="more-actions"><summary>更多</summary><button disabled={Boolean(pendingAction)} onClick={() => void toggle(source)}>{pendingAction === `toggle:${source.id}` ? '正在处理…' : source.enabled ? '停用' : '启用'}</button><button className="danger" disabled={Boolean(pendingAction)} onClick={() => void archive(source)}>{pendingAction === `archive:${source.id}` ? '正在归档…' : '归档'}</button></details></td></tr>)}</tbody></table></div>}</Panel>
  </>
}
