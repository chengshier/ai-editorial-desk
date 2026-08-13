import { useEffect, type ReactNode } from 'react'
import { AlertTriangle, Inbox, X } from 'lucide-react'

export function Panel({ title, actions, children, className = '' }: { title: string; actions?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`.trim()}><div className="panel-head"><h2>{title}</h2>{actions}</div>{children}</section>
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

function localDateTimeParts(value: string) {
  const [date = '', rawTime = ''] = value.split('T')
  return { date, time: rawTime.slice(0, 5) }
}

function localNowParts() {
  const now = new Date()
  const offset = now.getTimezoneOffset() * 60_000
  const local = new Date(now.getTime() - offset).toISOString().slice(0, 16)
  return localDateTimeParts(local)
}

export function DateTimeField({
  label,
  value,
  onChange,
  dateAriaLabel,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  dateAriaLabel?: string
}) {
  const { date, time } = localDateTimeParts(value)
  const setDate = (nextDate: string) => {
    if (!nextDate) return onChange('')
    onChange(`${nextDate}T${time || '12:00'}`)
  }
  const setTime = (nextTime: string) => {
    if (!nextTime && !date) return onChange('')
    const nextDate = date || localNowParts().date
    onChange(`${nextDate}T${nextTime || '00:00'}`)
  }
  const useNow = () => {
    const now = localNowParts()
    onChange(`${now.date}T${now.time}`)
  }

  return <div className="datetime-field field-full">
    <span className="field-label">{label}</span>
    <div className="datetime-controls">
      <label><span>日期</span><input aria-label={dateAriaLabel || label} type="date" value={date} onChange={(event) => setDate(event.target.value)}/></label>
      <label><span>时间</span><input aria-label={`${label}时间`} type="time" step="60" value={time} onChange={(event) => setTime(event.target.value)}/></label>
      <button type="button" className="secondary datetime-now" onClick={useNow}>使用当前时间</button>
    </div>
  </div>
}

export function Drawer({
  open,
  title,
  description,
  children,
  footer,
  onClose,
  width = 'normal',
}: {
  open: boolean
  title: string
  description?: string
  children: ReactNode
  footer?: ReactNode
  onClose: () => void
  width?: 'normal' | 'wide'
}) {
  useEffect(() => {
    if (!open) return
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', handleKey)
      document.body.style.overflow = previous
    }
  }, [open, onClose])

  if (!open) return null
  return <div className="drawer-layer" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose() }}>
    <section className={`drawer drawer-${width}`} role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}>
      <header className="drawer-head">
        <div><h2>{title}</h2>{description && <p>{description}</p>}</div>
        <button className="icon-button" aria-label="关闭" title="关闭" onClick={onClose}><X size={18}/></button>
      </header>
      <div className="drawer-body">{children}</div>
      {footer && <footer className="drawer-footer">{footer}</footer>}
    </section>
  </div>
}

export function ResourceHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: string
  actions?: ReactNode
}) {
  return <div className="resource-header"><div><h2>{title}</h2>{description && <p>{description}</p>}</div>{actions && <div className="resource-actions">{actions}</div>}</div>
}
