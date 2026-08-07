import type { Page } from './types'

export type SessionConfig = {
  apiBaseUrl: string
  adminToken: string
  actorId: string
}

const STORAGE_KEY = 'ai-editorial-m1-admin-session'

const defaultConfig = (): SessionConfig => ({
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000',
  adminToken: '',
  actorId: '',
})

export function loadSessionConfig(): SessionConfig {
  const raw = sessionStorage.getItem(STORAGE_KEY)
  if (!raw) return defaultConfig()
  try {
    return { ...defaultConfig(), ...(JSON.parse(raw) as Partial<SessionConfig>) }
  } catch {
    return defaultConfig()
  }
}

export function saveSessionConfig(config: SessionConfig): void {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(config))
}

export function clearSessionConfig(): void {
  sessionStorage.removeItem(STORAGE_KEY)
}

export class AdminApi {
  constructor(private readonly config: SessionConfig) {}

  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const method = (init.method || 'GET').toUpperCase()
    const headers = new Headers(init.headers)
    headers.set('Accept', 'application/json')
    if (init.body) headers.set('Content-Type', 'application/json')
    if (this.config.adminToken) headers.set('X-Admin-Token', this.config.adminToken)
    if (method !== 'GET' && method !== 'HEAD' && this.config.actorId) {
      headers.set('X-Actor-ID', this.config.actorId)
    }
    const response = await fetch(`${this.config.apiBaseUrl}${path}`, { ...init, headers })
    if (!response.ok) {
      let message = `请求失败 (${response.status})`
      try {
        const payload = await response.json() as { detail?: string | { message?: string } }
        if (typeof payload.detail === 'string') message = payload.detail
        else if (payload.detail?.message) message = payload.detail.message
      } catch {
        // Intentionally do not log request headers or token-bearing config.
      }
      throw new Error(message)
    }
    return response.json() as Promise<T>
  }

  page<T>(path: string): Promise<Page<T>> {
    return this.request<Page<T>>(path)
  }

  post<T>(path: string, body: unknown = {}): Promise<T> {
    return this.request<T>(path, { method: 'POST', body: JSON.stringify(body) })
  }

  patch<T>(path: string, body: unknown): Promise<T> {
    return this.request<T>(path, { method: 'PATCH', body: JSON.stringify(body) })
  }
}
