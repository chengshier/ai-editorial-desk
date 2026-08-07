import { useCallback, useEffect, useState } from 'react'
import { AdminApi } from '../api'
import { ErrorBanner, Panel } from '../components/common'
import type { Account, RiskEvent } from '../types'

export function AccountsRiskPage({ api }: { api: AdminApi }) {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [risks, setRisks] = useState<RiskEvent[]>([])
  const [error, setError] = useState<string | null>(null)

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
    }
  }

  return <>
    <Panel title="Platform Accounts">
      <ErrorBanner error={error}/>
      <p className="notice">页面只显示凭据是否已配置，不读取 Cookie、Token、credential_ref 或 browser_profile_ref 原值。</p>
      <div className="table-wrap"><table><thead><tr><th>账号</th><th>平台</th><th>状态</th><th>人工复核</th><th>冷却</th><th>操作</th></tr></thead><tbody>{accounts.map((account) => <tr key={account.id}><td>{account.display_name}</td><td>{account.platform}</td><td>{account.status}</td><td>{account.manual_review_required ? '是' : '否'}</td><td>{account.cooldown_until || '-'}</td><td className="actions"><button onClick={() => void transition(account.id, 'review_required')}>进入 REVIEW</button>{account.status !== 'healthy' && <button onClick={() => void transition(account.id, 'healthy')}>按状态机恢复</button>}</td></tr>)}</tbody></table></div>
    </Panel>
    <Panel title="Recent Risk Events">
      <div className="table-wrap"><table><thead><tr><th>时间</th><th>平台</th><th>风险</th><th>级别</th><th>动作</th></tr></thead><tbody>{risks.map((risk) => <tr key={risk.id}><td>{new Date(risk.created_at).toLocaleString()}</td><td>{risk.platform}</td><td>{risk.risk_type}</td><td>{risk.risk_level}</td><td>{risk.action_taken || '-'}</td></tr>)}</tbody></table></div>
    </Panel>
  </>
}
