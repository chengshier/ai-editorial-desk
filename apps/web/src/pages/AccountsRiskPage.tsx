import { useCallback, useEffect, useState } from 'react'
import { AdminApi } from '../api'
import { ErrorBanner, Panel } from '../components/common'
import { accountStatusLabel, booleanLabel } from '../uiLabels'
import type { Account, RiskEvent } from '../types'

export function AccountsRiskPage({ api }: { api: AdminApi }) {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [risks, setRisks] = useState<RiskEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const [resolvingRiskId, setResolvingRiskId] = useState<string | null>(null)
  const [resolutionNote, setResolutionNote] = useState('')
  const [pendingAction, setPendingAction] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [accountPage, riskPage] = await Promise.all([
        api.page<Account>('/api/v1/admin/platform-accounts?page_size=100'),
        api.page<RiskEvent>('/api/v1/admin/platform-risk-events?page_size=100'),
      ])
      setAccounts(accountPage.items)
      setRisks(riskPage.items)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [api])

  useEffect(() => {
    void load()
  }, [load])

  const transition = async (id: string, target_status: string) => {
    setPendingAction(`account:${id}`)
    setError(null)
    try {
      await api.post(`/api/v1/admin/platform-accounts/${id}/status`, {
        target_status,
        reason: 'Web 管理员操作',
        cooldown_until: null,
        override_cooldown: false,
      })
      await load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPendingAction(null)
    }
  }

  const resolveRisk = async (risk: RiskEvent) => {
    if (!resolutionNote.trim()) return setError('请填写风险处理说明')
    setPendingAction(`risk:${risk.id}`)
    setError(null)
    try {
      await api.post(`/api/v1/admin/platform-risk-events/${risk.id}/resolve`, { resolution_note: resolutionNote.trim() })
      setResolvingRiskId(null)
      setResolutionNote('')
      await load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPendingAction(null)
    }
  }

  return <>
    <Panel title="平台账号" actions={<button onClick={() => void load()}>刷新</button>}>
      <ErrorBanner error={error}/>
      <p className="notice">页面只显示凭据是否已配置，不读取 Cookie、Token、credential_ref 或 browser_profile_ref 原值。</p>
      {accounts.length===0?<div className="empty">暂无平台账号</div>:<div className="table-wrap"><table><thead><tr><th>账号</th><th>平台</th><th>当前状态</th><th>需要人工处理</th><th>冷却状态</th><th>操作</th></tr></thead><tbody>{accounts.map((account) => <tr key={account.id}><td>{account.display_name}</td><td>{account.platform}</td><td>{accountStatusLabel[account.status]||account.status}</td><td>{booleanLabel(account.manual_review_required)}</td><td>{account.cooldown_until || '无'}</td><td className="actions"><button disabled={Boolean(pendingAction)} onClick={() => void transition(account.id, 'review_required')}>{pendingAction === `account:${account.id}` ? '正在处理…' : '进入人工复核'}</button>{account.status !== 'healthy' && <button disabled={Boolean(pendingAction)} onClick={() => void transition(account.id, 'healthy')}>按状态机恢复</button>}</td></tr>)}</tbody></table></div>}
    </Panel>
    <Panel title="最近风险事件">
      {risks.length===0?<div className="empty">暂无风险事件</div>:<div className="table-wrap"><table><thead><tr><th>时间</th><th>平台</th><th>风险原因</th><th>风险等级</th><th>当前处理状态</th><th>操作</th></tr></thead><tbody>{risks.map((risk) => <tr key={risk.id}><td>{new Date(risk.created_at).toLocaleString()}</td><td>{risk.platform}</td><td>{risk.risk_type}</td><td>{risk.risk_level}</td><td>{risk.resolved_at ? `已解决：${risk.resolution_note || '无说明'}` : risk.action_taken || '暂无'}</td><td>{risk.resolved_at ? '已解决' : resolvingRiskId === risk.id ? <div className="risk-resolution"><label>风险处理说明<input aria-label="风险处理说明" value={resolutionNote} onChange={(event) => setResolutionNote(event.target.value)} /></label><button className="primary" disabled={Boolean(pendingAction)} onClick={() => void resolveRisk(risk)}>{pendingAction === `risk:${risk.id}` ? '正在提交…' : '标记为已解决'}</button><button disabled={Boolean(pendingAction)} onClick={() => { setResolvingRiskId(null); setResolutionNote('') }}>取消</button></div> : <button onClick={() => { setResolvingRiskId(risk.id); setResolutionNote('') }}>处理风险事件</button>}</td></tr>)}</tbody></table></div>}
    </Panel>
  </>
}
