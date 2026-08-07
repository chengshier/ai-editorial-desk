import { useMemo } from 'react'
import type { JsonSchema, UiSchema, VisibilityRule } from '../types'

type Props = {
  schema: JsonSchema
  uiSchema?: UiSchema
  value: Record<string, unknown>
  onChange: (value: Record<string, unknown>) => void
}

type Primitive = string | number | boolean

function parseArray(raw: string, itemSchema?: JsonSchema): Primitive[] {
  const values = raw.split(',').map((item) => item.trim()).filter(Boolean)
  if (itemSchema?.type === 'integer') return values.map((item) => Number.parseInt(item, 10))
  if (itemSchema?.type === 'number') return values.map(Number)
  if (itemSchema?.type === 'boolean') return values.map((item) => item === 'true')
  return values
}

function normalizeDefault(schema: JsonSchema): unknown {
  if (schema.default !== undefined) return schema.default
  if (schema.type === 'boolean') return false
  if (schema.type === 'array') return []
  if (schema.type === 'integer' || schema.type === 'number') return ''
  return ''
}

function isVisible(rule: VisibilityRule | undefined, value: Record<string, unknown>): boolean {
  if (!rule) return true
  const current = value[rule.field]
  if (rule.equals !== undefined) return current === rule.equals
  if (rule.contains !== undefined) return Array.isArray(current) && current.includes(rule.contains)
  if (rule.contains_any !== undefined) {
    return Array.isArray(current) && rule.contains_any.some((item) => current.includes(item))
  }
  return true
}

export function validateSchemaValue(
  schema: JsonSchema,
  value: Record<string, unknown>,
  uiSchema: UiSchema = {},
): Record<string, string> {
  const errors: Record<string, string> = {}
  for (const required of schema.required || []) {
    if (!isVisible(uiSchema[required]?.visible_when, value)) continue
    const current = value[required]
    if (current === undefined || current === null || current === '' || (Array.isArray(current) && current.length === 0)) {
      errors[required] = '必填项'
    }
  }
  for (const [key, field] of Object.entries(schema.properties || {})) {
    if (!isVisible(uiSchema[key]?.visible_when, value) || errors[key]) continue
    const current = value[key]
    if (typeof current === 'number') {
      if (field.minimum !== undefined && current < field.minimum) errors[key] = `不得小于 ${field.minimum}`
      if (field.maximum !== undefined && current > field.maximum) errors[key] = `不得大于 ${field.maximum}`
    }
    if (typeof current === 'string') {
      if (field.minLength !== undefined && current.length < field.minLength) errors[key] = `至少 ${field.minLength} 个字符`
      if (field.maxLength !== undefined && current.length > field.maxLength) errors[key] = `最多 ${field.maxLength} 个字符`
    }
    if (Array.isArray(current)) {
      if (field.minItems !== undefined && current.length < field.minItems) errors[key] = `至少 ${field.minItems} 项`
      if (field.maxItems !== undefined && current.length > field.maxItems) errors[key] = `最多 ${field.maxItems} 项`
    }
  }
  return errors
}

export function SchemaForm({ schema, uiSchema = {}, value, onChange }: Props) {
  const properties = useMemo(() => Object.entries(schema.properties || {}).sort(([a], [b]) => {
    return (uiSchema[a]?.order ?? 999) - (uiSchema[b]?.order ?? 999)
  }), [schema.properties, uiSchema])
  const errors = validateSchemaValue(schema, value, uiSchema)

  const set = (key: string, next: unknown) => onChange({ ...value, [key]: next })

  return <div className="schema-form" data-testid="schema-form">
    {properties.map(([key, field]) => {
      const ui = uiSchema[key] || {}
      if (!isVisible(ui.visible_when, value)) return null
      const label = ui.label || field.title || key
      const current = value[key] ?? normalizeDefault(field)
      const required = schema.required?.includes(key)
      const secretHint = ui.secret_reference || ui.widget === 'secret_reference'
      const checkboxOptions = field.type === 'array' && ui.widget === 'checkbox_group' ? field.items?.enum : undefined
      return <div className="field" key={key}>
        <span>{label}{required ? ' *' : ''}</span>
        {checkboxOptions ? <div role="group" aria-label={label}>
          {checkboxOptions.map((option) => {
            const checked = Array.isArray(current) && current.includes(option)
            return <label key={String(option)}>
              <input
                type="checkbox"
                checked={checked}
                onChange={(event) => {
                  const values = Array.isArray(current) ? [...current] : []
                  const next = event.target.checked
                    ? [...values.filter((item) => item !== option), option]
                    : values.filter((item) => item !== option)
                  set(key, next)
                }}
              />
              {String(option)}
            </label>
          })}
        </div> : field.enum ? <select aria-label={label} value={String(current)} onChange={(event) => {
          const selected = event.target.value
          set(key, field.type === 'integer' || field.type === 'number' ? Number(selected) : selected)
        }}>
          <option value="">请选择</option>
          {field.enum.map((option) => <option key={String(option)} value={String(option)}>{String(option)}</option>)}
        </select> : field.type === 'boolean' ? <input
          aria-label={label}
          type="checkbox"
          checked={Boolean(current)}
          onChange={(event) => set(key, event.target.checked)}
        /> : field.type === 'array' ? <input
          aria-label={label}
          value={Array.isArray(current) ? current.join(', ') : ''}
          placeholder="多项请用逗号分隔"
          onChange={(event) => set(key, parseArray(event.target.value, field.items))}
        /> : <input
          aria-label={label}
          type={field.type === 'number' || field.type === 'integer' ? 'number' : 'text'}
          value={String(current)}
          min={field.minimum}
          max={field.maximum}
          onChange={(event) => {
            if (field.type === 'integer') set(key, event.target.value === '' ? '' : Number.parseInt(event.target.value, 10))
            else if (field.type === 'number') set(key, event.target.value === '' ? '' : Number(event.target.value))
            else set(key, event.target.value)
          }}
        />}
        {(ui.help || field.description) && <small>{ui.help || field.description}</small>}
        {secretHint && <small className="warning">这里只填写凭据引用，不显示或读取真实 Secret。</small>}
        {errors[key] && <small className="error" role="alert">{errors[key]}</small>}
      </div>
    })}
  </div>
}
