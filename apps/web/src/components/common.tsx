import type { ReactNode } from 'react'
import { AlertTriangle, Inbox } from 'lucide-react'

export function Panel({ title, actions, children }: { title: string; actions?: ReactNode; children: ReactNode }) {
  return <section className="panel"><div className="panel-head"><h2>{title}</h2>{actions}</div>{children}</section>
}

export function ErrorBanner({ error }: { error: string | null }) {
  const message=error==='Failed to fetch'?'无法连接服务。请确认 API Base、后端服务和网络连接后重试。':error
  return message ? <div className="error-banner" role="alert"><AlertTriangle size={17} aria-hidden="true"/><span>{message}</span></div> : null
}

export function JsonView({ value }: { value: unknown }) {
  return <pre className="json-view">{JSON.stringify(value, null, 2)}</pre>
}

export function Empty({ text = '暂无数据', helper = '当前没有可展示的记录。', action }: { text?: string; helper?: string; action?: ReactNode }) {
  return <div className="empty" role="status"><Inbox size={24} aria-hidden="true"/><strong>{text}</strong><span>{helper}</span>{action}</div>
}
