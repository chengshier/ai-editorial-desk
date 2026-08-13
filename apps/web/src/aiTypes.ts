export type AiProvider = {
  id: string
  provider_key: string
  display_name: string
  provider_type: string
  base_url: string
  credential_configured: boolean
  credential_ref_masked: string | null
  enabled: boolean
  validation_status: 'NOT_TESTED' | 'PASSED' | 'FAILED'
  last_validated_at: string | null
  timeout_seconds: number
  max_concurrency: number
  retry_limit: number
  config: Record<string, unknown>
  model_count: number
  last_invocation_at: string | null
  error_rate: number | null
  created_at: string
  updated_at: string
}

export type AiModel = {
  id: string
  provider_id: string
  model_key: string
  model_name: string
  capabilities: string[]
  enabled: boolean
  context_window: number | null
  input_price_per_million: string | null
  output_price_per_million: string | null
  embedding_price_per_million: string | null
  pricing_version: string
  dimensions: number | null
  config: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type AiGenerationPolicy = Record<string, unknown> & {
  max_output_tokens?: number
}

export type AiRouteConfig = Record<string, unknown> & {
  generation_policy?: AiGenerationPolicy
}

export type AiRoute = {
  id: string
  task_key: string
  version: number
  primary_model_id: string | null
  fallback_model_ids: string[]
  timeout_seconds: number
  retry_limit: number
  budget_policy: Record<string, unknown>
  config: AiRouteConfig
  enabled: boolean
  is_active: boolean
  created_at: string
}

export type AiBudget = {
  id: string
  scope_type: 'global' | 'task' | 'provider'
  scope_key: string
  enabled: boolean
  daily_cost_limit: string | null
  monthly_cost_limit: string | null
  daily_token_limit: number | null
  unknown_usage_policy: 'block' | 'allow_once'
  config: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type AiInvocation = {
  id: string
  task_key: string
  route_version: number
  provider_key: string | null
  model_name: string | null
  capability: string
  status: string
  input_hash: string
  prompt_version: string | null
  schema_version: string | null
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
  estimated_cost: string | null
  latency_ms: number | null
  retry_count: number
  fallback_index: number
  provider_request_id: string | null
  subject_type: string | null
  subject_id: string | null
  pricing_snapshot: Record<string, unknown>
  metadata: Record<string, unknown>
  started_at: string
  finished_at: string | null
  error_code: string | null
}

export type AiInvocationAttempt = {
  id: string
  attempt_no: number
  retry_index: number
  fallback_index: number
  provider_key: string
  model_name: string
  status: string
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
  estimated_cost: string | null
  latency_ms: number | null
  provider_request_id: string | null
  error_code: string | null
  error_message: string | null
  started_at: string
  finished_at: string | null
}

export type AiInvocationDetail = AiInvocation & { attempts: AiInvocationAttempt[] }
