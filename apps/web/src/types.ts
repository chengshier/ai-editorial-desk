export type JsonSchema = {
  type?: string
  title?: string
  description?: string
  required?: string[]
  properties?: Record<string, JsonSchema>
  items?: JsonSchema
  enum?: Array<string | number>
  const?: unknown
  default?: unknown
  minimum?: number
  maximum?: number
  minLength?: number
  maxLength?: number
  minItems?: number
  maxItems?: number
  uniqueItems?: boolean
}

type Primitive = string | number | boolean

export type VisibilityRule = {
  field: string
  equals?: Primitive
  contains?: Primitive
  contains_any?: Primitive[]
}

export type UiSchema = Record<string, {
  label?: string
  help?: string
  order?: number
  widget?: string
  secret_reference?: boolean
  visible_when?: VisibilityRule
}>

export type Page<T> = {
  items: T[]
  page: number
  page_size: number
  total: number
  has_next: boolean
}

export type Definition = {
  id: string
  display_name: string
  connector_type: string
  platform: string
  registered: boolean
  implemented: boolean
  enabled: boolean
  validated: boolean
  implementation_version: string
  capabilities: Record<string, unknown>
  config_schema: JsonSchema
  ui_schema: UiSchema
}

export type Instance = {
  id: string
  definition_id: string
  name: string
  enabled: boolean
  status: string
  config: Record<string, unknown>
  config_version: number
}

export type Source = {
  id: string
  connector_instance_id: string
  name: string
  source_type: string
  mode: string
  scope_key: string
  external_ref?: string | null
  config: Record<string, unknown>
  enabled: boolean
  status: string
}

export type Schedule = {
  id: string
  connector_instance_id: string
  source_id: string
  platform_account_id?: string | null
  name: string
  enabled: boolean
  schedule_type: 'interval' | 'cron'
  interval_seconds?: number | null
  cron_expression?: string | null
  timezone: string
  requested_limit: number
  next_run_at: string
  last_triggered_at?: string | null
  last_run_id?: string | null
  consecutive_failures: number
  paused_reason?: string | null
}

export type Run = {
  id: string
  connector_instance_id: string
  source_id?: string | null
  platform_account_id?: string | null
  parent_run_id?: string | null
  trigger_type: string
  mode: string
  status: string
  started_at?: string | null
  progress_updated_at?: string | null
  finished_at?: string | null
  requested_limit: number
  collected_count: number
  inserted_count: number
  duplicate_count: number
  failed_count: number
  retry_count: number
  error_code?: string | null
  error_message?: string | null
  checkpoint_before?: Record<string, unknown> | null
  checkpoint_after?: Record<string, unknown> | null
  budget?: unknown
  risk_action?: unknown
  metadata: Record<string, unknown>
  latency_seconds?: number | null
  created_at: string
}

export type Checkpoint = {
  id: string
  connector_instance_id: string
  source_id?: string | null
  platform_account_id?: string | null
  mode: string
  scope_key: string
  cursor?: Record<string, unknown> | null
  watermark?: string | null
  last_external_id?: string | null
  last_published_at?: string | null
  checkpoint_data: Record<string, unknown>
  version: number
  updated_at: string
}

export type Account = {
  id: string
  connector_instance_id: string
  platform: string
  display_name: string
  status: string
  cooldown_until?: string | null
  manual_review_required: boolean
  credential_configured?: boolean
  browser_profile_configured?: boolean
}

export type RiskEvent = {
  id: string
  platform: string
  risk_type: string
  risk_level: string
  message?: string | null
  action_taken?: string | null
  manual_review_required: boolean
  created_at: string
  resolved_at?: string | null
  resolution_note?: string | null
}
