import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SchemaForm, validateSchemaValue } from './SchemaForm'
import type { JsonSchema } from '../types'

const schema: JsonSchema = {
  type: 'object',
  required: ['name', 'limit'],
  properties: {
    name: { type: 'string', minLength: 2, description: '显示名称' },
    limit: { type: 'integer', minimum: 1, maximum: 100, default: 20 },
    enabled: { type: 'boolean', default: true },
    mode: { type: 'string', enum: ['feed', 'hotlist'] },
    tags: { type: 'array', items: { type: 'string' }, minItems: 1 },
    credential_ref: { type: 'string' },
  },
}

it('renders primitive JSON Schema fields and UI hints', async () => {
  const user = userEvent.setup()
  let value: Record<string, unknown> = { name: '', limit: 20, tags: [] }
  const { rerender } = render(<SchemaForm schema={schema} uiSchema={{ credential_ref: { label: '凭据引用', widget: 'secret_reference', order: 1 } }} value={value} onChange={(next) => { value = next }} />)
  expect(screen.getByText('凭据引用')).toBeInTheDocument()
  expect(screen.getByText(/不显示或读取真实 Secret/)).toBeInTheDocument()
  expect(screen.getAllByRole('alert').some((item) => item.textContent === '必填项')).toBe(true)
  const name = screen.getByLabelText(/name/i)
  await user.type(name, 'A')
  rerender(<SchemaForm schema={schema} value={{ ...value, name: 'A' }} onChange={() => undefined} />)
  expect(screen.getByText(/至少 2 个字符/)).toBeInTheDocument()
})

it('validates min/max and required without replacing backend validation', () => {
  expect(validateSchemaValue(schema, { name: 'ok', limit: 101, tags: ['a'] }).limit).toBe('不得大于 100')
  expect(validateSchemaValue(schema, { name: '', limit: 2, tags: [] }).name).toBe('必填项')
})
