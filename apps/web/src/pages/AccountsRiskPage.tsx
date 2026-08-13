import { useCallback, useEffect, useMemo, useState } from 'react'
import { AdminApi } from '../api'
import { Drawer, Empty, ErrorBanner, ResourceHeader } from '../components/common'
import { accountStatusLabel, booleanLabel } from '../uiLabels'
import type { Account, Instance, RiskEvent } from '../types'

type AccountForm = {
  connector_instance_id: string
  display_name: string
  account_identifier: string
  credential_ref: string
  browser_profile_ref: string
}

type BrowserRuntimeStatus = {
  status: string
  enabled: boolean
  browser_name: string | null
  cdp_ready: boolean
  managed_by_api: boolean
  profile_configured: boolean
  profile_ready: boolean
  can_start: boolean
  can_stop: boolean
  can_open_login: boolean
  cdp_host: string
  cdp_port: number
  message: string
}

const emptyAccountForm: AccountForm = {
  connector_instance_id: '',
  display_name: '',
  account_identifier: '',
  credential_ref: '',
  browser_profile_ref: '',
}

function browserStatusLabel(status: BrowserRuntimeStatus | null): string {
  if (!status) return '正在读取浏览器状态…'
  const labels: Record<string, string> = {
    RUNNING: '专用浏览器已就绪',
    RUNNING_EXTERNAL: '检测到外部浏览器',
    STOPPED: '专用浏览器未启动',
    PROFILE_REQUIRED: '需要配置 Browser Profile',
    BROWSER_NOT_FOUND: '未检测到 Chrome / Edge',
    CONFLICT: '其他账号正在使用专用浏览器',
    UNAVAILABLE: '当前部署不支持本机浏览器运行器',
  }
  return labels[status.status] || status.status
}

export function AccountsRiskPage({ api }: { api: AdminApi }) {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [instances, setInstances] = useState<Instance[]>([])
  const [risks, setRisks] = useState<RiskEvent[]>([])
  const [pageError, setPageError] = useState<string | null>(null)
  const [drawerError, setDrawerError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [resolvingRiskId, setResolvingRiskId] = useState<string | null>(null)
  const [resolutionNote, setResolutionNote] = useState('')
  const [pendingAction, setPendingAction] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editing, setEditing] = useState<Account | null>(null)
  const [form, setForm] = useState<AccountForm>(emptyAccountForm)
  const [browserDrawerOpen, setBrowserDrawerOpen] = useState(false)
  const [browserAccount, setBrowserAccount] = useState<Account | null>(null)
  const [browserStatus, setBrowserStatus] = useState<BrowserRuntimeStatus | null>(null)
  const [browserError, setBrowserError] = useState<string | null>(null)
  const [browserPending, setBrowserPending] = useState<string | null>(null)

  const selectedInstance = useMemo(
    () => instances.find((item) => item.id === form.connector_instance_id) || null,
    [instances, form.connector_instance_id],
  )

  const load = useCallback(async () => {
    try {
      const [accountPage, instancePage, riskPage] = await Promise.all([
        api.page<Account>('/api/v1/admin/platform-accounts?page_size=100'),
        api.page<Instance>('/api/v1/admin/connector-instances?page_size=100'),
        api.page<RiskEvent>('/api/v1/admin/platform-risk-events?page_size=100'),
      ])
      setAccounts(accountPage.items)
      setInstances(instancePage.items)
      setRisks(riskPage.items)
      setPageError(null)
    } catch (e) {
      setPageError((e as Error).message)
    }
  }, [api])

  useEffect(() => {
    void load()
  }, [load])

  const resetAccountForm = () => {
    setEditing(null)
    setDrawerError(null)
    setForm({ ...emptyAccountForm, connector_instance_id: instances[0]?.id || '' })
  }

  const openCreate = () => {
    resetAccountForm()
    setMessage(null)
    setDrawerOpen(true)
  }

  const openEdit = (account: Account) => {
    setEditing(account)
    setDrawerError(null)
    setMessage(null)
    setForm({
      connector_instance_id: account.connector_instance_id,
      display_name: account.display_name,
      account_identifier: account.account_identifier,
      credential_ref: '',
      browser_profile_ref: '',
    })
    setDrawerOpen(true)
  }

  const saveAccount = async () => {
    const instance = selectedInstance
    if (!instance) return setDrawerError('请选择连接器实例')
    if (!form.display_name.trim()) return setDrawerError('请填写账号显示名称')
    if (!editing && !form.account_identifier.trim()) return setDrawerError('请填写平台账号标识')
    setPendingAction('save-account')
    setDrawerError(null)
    try {
      if (editing) {
        const changes: Record<string, unknown> = { display_name: form.display_name.trim() }
        if (form.credential_ref.trim()) changes.credential_ref = form.credential_ref.trim()
        if (form.browser_profile_ref.trim()) changes.browser_profile_ref = form.browser_profile_ref.trim()
        await api.patch(`/api/v1/admin/platform-accounts/${editing.id}`, changes)
        setMessage('平台账号配置已更新。')
      } else {
        await api.post('/api/v1/admin/platform-accounts', {
          connector_instance_id: instance.id,
          platform: instance.platform,
          display_name: form.display_name.trim(),
          account_identifier: form.account_identifier.trim(),
          credential_ref: form.credential_ref.trim() || null,
          browser_profile_ref: form.browser_profile_ref.trim() || null,
        })
        setMessage('平台账号已创建。配置专用 Browser Profile 后，可一键启动登录浏览器。')
      }
      await load()
      setDrawerOpen(false)
      resetAccountForm()
    } catch (e) {
      setDrawerError((e as Error).message)
    } finally {
      setPendingAction(null)
    }
  }

  const transition = async (id: string, target_status: string) => {
    setPendingAction(`account:${id}`)
    setPageError(null)
    try {
      await api.post(`/api/v1/admin/platform-accounts/${id}/status`, {
        target_status,
        reason: 'Web 管理员操作',
        cooldown_until: null,
        override_cooldown: false,
      })
      setMessage(target_status === 'healthy' ? '账号已按状态机恢复。' : '账号已进入人工复核。')
      await load()
    } catch (e) {
      setPageError((e as Error).message)
    } finally {
      setPendingAction(null)
    }
  }

  const resolveRisk = async (risk: RiskEvent) => {
    if (!resolutionNote.trim()) return setPageError('请填写风险处理说明')
    setPendingAction(`risk:${risk.id}`)
    setPageError(null)
    try {
      await api.post(`/api/v1/admin/platform-risk-events/${risk.id}/resolve`, { resolution_note: resolutionNote.trim() })
      setResolvingRiskId(null)
      setResolutionNote('')
      setMessage('风险事件已标记为解决。')
      await load()
    } catch (e) {
      setPageError((e as Error).message)
    } finally {
      setPendingAction(null)
    }
  }

  const loadBrowserStatus = async (account: Account) => {
    setBrowserPending('status')
    setBrowserError(null)
    try {
      const result = await api.request<BrowserRuntimeStatus>(`/api/v1/admin/platform-accounts/${account.id}/browser-runtime`)
      setBrowserStatus(result)
    } catch (e) {
      setBrowserStatus(null)
      setBrowserError(e instanceof Error ? e.message : '读取专用浏览器状态失败')
    } finally {
      setBrowserPending(null)
    }
  }

  const openBrowserEnvironment = (account: Account) => {
    setBrowserAccount(account)
    setBrowserStatus(null)
    setBrowserError(null)
    setBrowserDrawerOpen(true)
    void loadBrowserStatus(account)
  }

  const browserAction = async (action: 'start' | 'stop' | 'open-login') => {
    if (!browserAccount) return
    if (action === 'open-login' && !window.confirm(`将在专用浏览器中打开 ${browserAccount.platform} 页面，仅用于人工登录。系统不会自动填写密码、绕过验证码或读取 Cookie 原值。继续？`)) return
    setBrowserPending(action)
    setBrowserError(null)
    try {
      const result = await api.post<BrowserRuntimeStatus>(`/api/v1/admin/platform-accounts/${browserAccount.id}/browser-runtime/${action}`)
      setBrowserStatus(result)
      if (action === 'start') setMessage('专用浏览器已启动。请在浏览器窗口中完成人工登录，然后回到信源执行采集前检查。')
      if (action === 'open-login') setMessage('已在专用浏览器中打开平台页面。登录完成后回到信源执行采集前检查。')
      if (action === 'stop') setMessage('专用浏览器已停止。')
    } catch (e) {
      setBrowserError(e instanceof Error ? e.message : '专用浏览器操作失败')
      await loadBrowserStatus(browserAccount)
    } finally {
      setBrowserPending(null)
    }
  }

  return <div className="operations-page account-risk-page">
    <ErrorBanner error={pageError}/>
    {message && <div className="success-banner">{message}</div>}

    <section className="panel">
      <ResourceHeader
        title="平台账号"
        description="需要登录态的采集连接器必须绑定平台账号。账号页只保存主系统引用关系；本地开发可直接从这里启动专用浏览器，无需记忆 CDP 命令。"
        actions={<><button onClick={() => void load()}>刷新</button><button className="primary" disabled={instances.length===0} title={instances.length===0?'请先创建连接器实例':''} onClick={openCreate}>新增平台账号</button></>}
      />
      <div className="notice account-safety-note">凭据字段填写的是主系统可解析的 <strong>credential_ref / browser_profile_ref</strong> 引用，不在页面展示真实 Cookie、Token 或浏览器目录。专用浏览器只使用受控 Profile，人工登录后再由采集前检查验证运行条件。</div>
      {instances.length===0 && <div className="prerequisite-hint">当前没有连接器实例。请先创建实例，再为需要登录态的平台绑定账号。</div>}
      {accounts.length===0 ? <Empty text="暂无平台账号" helper="B站、微博、知乎等 MediaCrawler 连接器需要平台账号与专用 Browser Profile 后才能完成采集前检查。" action={instances.length>0?<button className="primary" onClick={openCreate}>新增平台账号</button>:undefined}/> : <div className="table-wrap"><table><thead><tr><th>账号</th><th>所属实例</th><th>平台</th><th>凭据状态</th><th>当前状态</th><th>冷却 / 风险</th><th>操作</th></tr></thead><tbody>{accounts.map((account) => {
        const instance = instances.find((item) => item.id === account.connector_instance_id)
        return <tr key={account.id}>
          <td><strong>{account.display_name}</strong><small className="technical-meta">{account.account_identifier}</small></td>
          <td>{instance?.name || '未知实例'}</td>
          <td>{account.platform}</td>
          <td><div className="status-stack"><span>凭据：{booleanLabel(account.credential_configured)}</span><small>专用 Profile：{booleanLabel(account.browser_profile_configured)}</small></div></td>
          <td>{accountStatusLabel[account.status] || account.status}</td>
          <td><div className="status-stack"><span>{account.risk_level ? `风险 ${account.risk_level}` : '暂无风险等级'}</span><small>{account.cooldown_until ? `冷却至 ${new Date(account.cooldown_until).toLocaleString()}` : '无冷却'}</small></div></td>
          <td><div className="actions action-cell"><button className="primary" disabled={Boolean(pendingAction)} onClick={() => openBrowserEnvironment(account)}>浏览器环境</button><button disabled={Boolean(pendingAction)} onClick={() => openEdit(account)}>编辑配置</button><button disabled={Boolean(pendingAction)} onClick={() => void transition(account.id, 'review_required')}>{pendingAction === `account:${account.id}` ? '正在处理…' : '人工复核'}</button>{account.status !== 'healthy' && <button disabled={Boolean(pendingAction)} onClick={() => void transition(account.id, 'healthy')}>恢复</button>}</div></td>
        </tr>
      })}</tbody></table></div>}
    </section>

    <section className="panel">
      <ResourceHeader title="最近风险事件" description="风险事件来自 CollectorRuntime / Risk Guard。处理风险不会自动绕过平台限制，只记录人工处置结果。"/>
      {risks.length===0 ? <Empty text="暂无风险事件" helper="当前没有需要处理的平台风险记录。"/> : <div className="table-wrap"><table><thead><tr><th>时间</th><th>平台</th><th>风险原因</th><th>风险等级</th><th>当前处理状态</th><th>操作</th></tr></thead><tbody>{risks.map((risk) => <tr key={risk.id}><td>{new Date(risk.created_at).toLocaleString()}</td><td>{risk.platform}</td><td><strong>{risk.risk_type}</strong>{risk.message&&<small className="technical-meta">{risk.message}</small>}</td><td>{risk.risk_level}</td><td>{risk.resolved_at ? `已解决：${risk.resolution_note || '无说明'}` : risk.action_taken || '暂无'}</td><td>{risk.resolved_at ? '已解决' : resolvingRiskId === risk.id ? <div className="risk-resolution"><label>风险处理说明<input aria-label="风险处理说明" value={resolutionNote} onChange={(event) => setResolutionNote(event.target.value)} /></label><div className="actions"><button className="primary" disabled={Boolean(pendingAction)} onClick={() => void resolveRisk(risk)}>{pendingAction === `risk:${risk.id}` ? '正在提交…' : '标记为已解决'}</button><button disabled={Boolean(pendingAction)} onClick={() => { setResolvingRiskId(null); setResolutionNote('') }}>取消</button></div></div> : <button onClick={() => { setResolvingRiskId(risk.id); setResolutionNote('') }}>处理风险事件</button>}</td></tr>)}</tbody></table></div>}
    </section>

    <Drawer
      open={drawerOpen}
      width="wide"
      title={editing ? '编辑平台账号' : '新增平台账号'}
      description={editing ? '账号标识和所属实例保持创建时身份；如需更换凭据或 Browser Profile 引用，填写新的引用值即可。' : '先选择所属连接器实例，再填写平台账号标识与专用 Browser Profile 引用。'}
      onClose={() => { setDrawerOpen(false); resetAccountForm() }}
      footer={<><button disabled={pendingAction==='save-account'} onClick={() => { setDrawerOpen(false); resetAccountForm() }}>取消</button><button className="primary" disabled={pendingAction==='save-account'} onClick={() => void saveAccount()}>{pendingAction==='save-account'?'正在保存…':editing?'保存账号配置':'创建平台账号'}</button></>}
    >
      <ErrorBanner error={drawerError}/>
      <div className="drawer-section"><h3>账号归属</h3><p>账号必须与实际运行的连接器实例一致，运行时不会跨实例借用账号。</p><div className="form-grid"><label className="field-full">所属连接器实例<select disabled={Boolean(editing)} value={form.connector_instance_id} onChange={(event) => setForm({ ...form, connector_instance_id: event.target.value })}><option value="">请选择实例</option>{instances.map((instance) => <option key={instance.id} value={instance.id}>{instance.name} · {instance.platform}</option>)}</select></label><label>平台<input readOnly value={selectedInstance?.platform || editing?.platform || '选择实例后自动确定'}/></label><label>账号显示名称<input value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} placeholder="例如：B站采集账号 A"/></label><label className="field-full">平台账号标识<input disabled={Boolean(editing)} value={form.account_identifier} onChange={(event) => setForm({ ...form, account_identifier: event.target.value })} placeholder="平台内稳定账号标识；创建后不修改"/></label></div></div>
      <div className="drawer-section"><h3>登录态引用</h3><p>{editing ? '留空表示保持现有引用不变。页面不会读取或回显原始凭据值。' : 'Browser Profile 使用简短稳定名称，例如 bilibili-main；首次点击“启动专用浏览器”时系统会在受控目录自动创建对应 Profile。'}</p><div className="form-grid"><label className="field-full">凭据引用（credential_ref）<input value={form.credential_ref} onChange={(event) => setForm({ ...form, credential_ref: event.target.value })} placeholder={editing && editing.credential_configured?'已配置 · 留空保持不变':'例如环境变量或凭据存储引用'}/></label><label className="field-full">浏览器配置引用（browser_profile_ref）<input value={form.browser_profile_ref} onChange={(event) => setForm({ ...form, browser_profile_ref: event.target.value })} placeholder={editing && editing.browser_profile_configured?'已配置 · 留空保持不变':'可选，按运行环境的浏览器配置引用填写'}/><small>推荐格式：bilibili-main、zhihu-editor-01。不要填写绝对路径。</small></label></div></div>
    </Drawer>

    <Drawer
      open={browserDrawerOpen}
      width="wide"
      title={browserAccount ? `专用浏览器 · ${browserAccount.display_name}` : '专用浏览器'}
      description="把 CDP、端口和启动命令下沉为系统实现细节。启动动作本身不会访问平台；只有你点击“打开平台登录页”后才会导航到对应平台，登录仍由人工完成。"
      onClose={() => { setBrowserDrawerOpen(false); setBrowserAccount(null); setBrowserStatus(null); setBrowserError(null) }}
      footer={<button onClick={() => setBrowserDrawerOpen(false)}>关闭</button>}
    >
      <ErrorBanner error={browserError}/>
      <div className="drawer-section">
        <h3>{browserStatusLabel(browserStatus)}</h3>
        <p>{browserStatus?.message || (browserPending === 'status' ? '正在检测本机浏览器环境…' : '尚未读取运行状态。')}</p>
        {browserStatus && <div className="form-grid">
          <div className="field-full status-stack"><strong>浏览器</strong><span>{browserStatus.browser_name || '未检测到'}</span></div>
          <div className="status-stack"><strong>专用 Profile</strong><span>{browserStatus.profile_configured ? (browserStatus.profile_ready ? '已准备' : '已配置 · 首次启动时创建') : '未配置'}</span></div>
          <div className="status-stack"><strong>本机运行状态</strong><span>{browserStatus.cdp_ready ? '运行中' : '未启动'}</span></div>
        </div>}
        {browserStatus && !browserStatus.profile_configured && browserAccount && <div className="prerequisite-hint">请先配置 Browser Profile 引用。<button className="inline-link" onClick={() => { setBrowserDrawerOpen(false); openEdit(browserAccount) }}>编辑账号配置</button></div>}
        <div className="actions">
          <button className="primary" disabled={!browserStatus?.can_start || Boolean(browserPending)} onClick={() => void browserAction('start')}>{browserPending === 'start' ? '正在启动…' : '启动专用浏览器'}</button>
          <button disabled={!browserStatus?.can_open_login || Boolean(browserPending)} onClick={() => void browserAction('open-login')}>{browserPending === 'open-login' ? '正在打开…' : '打开平台登录页'}</button>
          <button disabled={!browserStatus?.can_stop || Boolean(browserPending)} onClick={() => void browserAction('stop')}>{browserPending === 'stop' ? '正在停止…' : '停止专用浏览器'}</button>
          {browserAccount && <button disabled={Boolean(browserPending)} onClick={() => void loadBrowserStatus(browserAccount)}>刷新状态</button>}
        </div>
        <div className="notice"><strong>安全边界：</strong>系统只启动自动检测或部署配置的 Chrome / Edge；调试端口固定监听本机 127.0.0.1；Web 不能传入任意命令、浏览器路径、端口或 URL；不会自动登录、不会绕过验证码。</div>
        {browserStatus && <details><summary>技术详情</summary><p>CDP：{browserStatus.cdp_host}:{browserStatus.cdp_port} · {browserStatus.managed_by_api ? '由当前后端管理' : '非当前后端托管'}。这些信息仅用于排查，正常使用无需手工执行命令。</p></details>}
      </div>
    </Drawer>
  </div>
}
