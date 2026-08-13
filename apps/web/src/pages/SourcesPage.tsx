import { useCallback, useEffect, useState } from 'react'
import { AdminApi } from '../api'
import { Drawer, Empty, ErrorBanner, ResourceHeader } from '../components/common'
import { enabledLabel, sourceModeLabel, sourceStatusLabel } from '../uiLabels'
import type { Instance, Source } from '../types'

const emptyForm = {
  connector_instance_id: '',
  name: '',
  source_type: 'rss',
  mode: 'feed',
  scope_key: '',
  external_ref: '',
}

export function SourcesPage({ api, onNavigate }: { api: AdminApi; onNavigate?: (page: 'runs') => void }) {
  const [sources, setSources] = useState<Source[]>([])
  const [instances, setInstances] = useState<Instance[]>([])
  const [editingId, setEditingId] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [form, setForm] = useState(emptyForm)
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
        setForm((current) => current.connector_instance_id ? current : { ...current, connector_instance_id: instancePage.items[0].id })
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
    setForm({ ...emptyForm, connector_instance_id: instances[0]?.id || '' })
  }

  const openCreate = () => {
    resetForm()
    setMessage(null)
    setError(null)
    setDrawerOpen(true)
  }

  const save = async () => {
    if (!form.connector_instance_id) return setError('请先选择所属连接器实例')
    if (!form.name.trim()) return setError('请填写信源名称')
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
      await load()
      setDrawerOpen(false)
      resetForm()
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
    setDrawerOpen(true)
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
    if (!source.enabled) return setError('该信源当前已停用，请先启用后再测试运行。')
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

  return <div className="operations-page">
    <ErrorBanner error={error}/>
    {message && <div className="success-banner"><span>{message}</span>{message.includes('运行') && onNavigate && <button className="quiet-action" onClick={() => onNavigate('runs')}>查看运行记录</button>}</div>}

    <section className="panel">
      <ResourceHeader
        title="信源"
        description="信源是实际被采集的数据入口。列表用于日常启停与测试，新增或编辑时再进入配置流程。"
        actions={<><button onClick={() => void load()}>刷新</button><button className="primary" disabled={instances.length===0} title={instances.length===0?'请先创建连接器实例':''} onClick={openCreate}>新建信源</button></>}
      />
      {instances.length===0&&<div className="prerequisite-hint">当前没有可用连接器实例，请先在“连接器实例”页面完成实例配置。</div>}
      {sources.length===0 ? <Empty text="暂无信源" helper="创建信源后，可在这里测试采集、启停信源并查看作用范围。" action={instances.length>0?<button className="primary" onClick={openCreate}>新建信源</button>:undefined}/> : <div className="table-wrap"><table><thead><tr><th>名称</th><th>所属实例</th><th>来源类型</th><th>采集模式</th><th>状态</th><th>操作</th></tr></thead><tbody>{sources.map((source) => {
        const instance=instances.find((item)=>item.id===source.connector_instance_id)
        return <tr key={source.id}>
          <td><strong>{source.name}</strong><small className="technical-meta">{source.scope_key}</small></td>
          <td>{instance?.name||'未知实例'}</td>
          <td>{source.source_type}</td>
          <td>{sourceModeLabel[source.mode]||source.mode}</td>
          <td>{source.enabled?enabledLabel(true):(sourceStatusLabel[source.status]||enabledLabel(false))}</td>
          <td><div className="actions action-cell"><button className="primary" disabled={Boolean(pendingAction)||!source.enabled} title={!source.enabled?'请先启用该信源':'创建一次少量测试运行'} onClick={() => void testRun(source)}>{pendingAction===`run:${source.id}`?'正在创建…':'测试运行'}</button><button disabled={Boolean(pendingAction)} onClick={() => edit(source)}>编辑</button><details className="more-actions"><summary>更多</summary><button disabled={Boolean(pendingAction)} onClick={() => void toggle(source)}>{pendingAction===`toggle:${source.id}`?'正在处理…':source.enabled?'停用':'启用'}</button><button className="danger" disabled={Boolean(pendingAction)} onClick={() => void archive(source)}>{pendingAction===`archive:${source.id}`?'正在归档…':'归档'}</button></details></div></td>
        </tr>
      })}</tbody></table></div>}
    </section>

    <Drawer
      open={drawerOpen}
      title={editingId?'编辑信源':'新建信源'}
      description={editingId?'名称和外部引用可修改；来源类型、采集模式和作用范围沿用创建时配置。':'选择所属实例并定义采集入口、模式和作用范围。'}
      onClose={() => { setDrawerOpen(false); resetForm() }}
      footer={<><button disabled={pendingAction==='save'} onClick={() => { setDrawerOpen(false); resetForm() }}>取消</button><button className="primary" disabled={pendingAction==='save'} onClick={() => void save()}>{pendingAction==='save'?'正在保存…':editingId?'保存修改':'创建信源'}</button></>}
    >
      <div className="drawer-section"><h3>来源归属</h3><p>先选择实际执行采集的连接器实例，再为该入口设置便于识别的名称。</p><div className="form-grid"><label className="field-full">所属实例<select disabled={Boolean(editingId)} value={form.connector_instance_id} onChange={(event) => setForm({ ...form, connector_instance_id: event.target.value })}><option value="">请选择实例</option>{instances.map((instance) => <option key={instance.id} value={instance.id}>{instance.name}</option>)}</select></label><label className="field-full">信源名称<input aria-label="信源名称" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如：B站科技热点"/></label></div></div>
      <div className="drawer-section"><h3>采集规则</h3><p>这些字段定义信源类型、采集方式和运行时作用范围；编辑已有信源时保持其原始身份不变。</p><div className="form-grid"><label>来源类型<input disabled={Boolean(editingId)} value={form.source_type} onChange={(event) => setForm({ ...form, source_type: event.target.value })}/></label><label>采集模式<select disabled={Boolean(editingId)} value={form.mode} onChange={(event) => setForm({ ...form, mode: event.target.value })}>{Object.entries(sourceModeLabel).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><label className="field-full">作用范围<input disabled={Boolean(editingId)} value={form.scope_key} onChange={(event) => setForm({ ...form, scope_key: event.target.value })} placeholder="用于区分采集范围的稳定标识"/></label><label className="field-full">外部引用<input value={form.external_ref} onChange={(event) => setForm({ ...form, external_ref: event.target.value })} placeholder="可选，例如 RSS URL 或外部来源引用"/></label></div></div>
    </Drawer>
  </div>
}
