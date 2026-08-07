import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SchemaForm, validateSchemaValue } from './SchemaForm'
import type { JsonSchema, UiSchema } from '../types'

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

it('renders M2-B mode checkboxes and conditional comment fields', async () => {
  const user = userEvent.setup()
  const m2bSchema: JsonSchema = {
    type: 'object',
    required: ['modes'],
    properties: {
      modes: { type: 'array', items: { type: 'string', enum: ['search', 'detail'] }, default: ['search'] },
      keyword: { type: 'string' },
      content_ids: { type: 'array', items: { type: 'string' } },
      include_comments: { type: 'boolean', default: false },
      comment_limit: { type: 'integer', minimum: 0, maximum: 50, default: 20 },
      include_subcomments: { type: 'boolean', default: false },
    },
  }
  const ui: UiSchema = {
    modes: { widget: 'checkbox_group', label: '采集模式' },
    keyword: { label: '关键词', visible_when: { field: 'modes', contains: 'search' } },
    content_ids: { label: '内容 ID', visible_when: { field: 'modes', contains: 'detail' } },
    include_comments: { label: '采集一级评论' },
    comment_limit: { label: '评论上限', visible_when: { field: 'include_comments', equals: true } },
    include_subcomments: { label: '采集二级评论', visible_when: { field: 'include_comments', equals: true } },
  }
  let value: Record<string, unknown> = { modes: ['search'], include_comments: false }
  const { rerender } = render(<SchemaForm schema={m2bSchema} uiSchema={ui} value={value} onChange={(next) => { value = next }} />)
  expect(screen.getByRole('group', { name: '采集模式' })).toBeInTheDocument()
  expect(screen.getByLabelText('关键词')).toBeInTheDocument()
  expect(screen.queryByLabelText('内容 ID')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('评论上限')).not.toBeInTheDocument()
  await user.click(screen.getByLabelText('采集一级评论'))
  rerender(<SchemaForm schema={m2bSchema} uiSchema={ui} value={value} onChange={(next) => { value = next }} />)
  expect(screen.getByLabelText('评论上限')).toBeInTheDocument()
  expect(screen.getByLabelText('采集二级评论')).toBeInTheDocument()
  await user.click(screen.getByLabelText('detail'))
  rerender(<SchemaForm schema={m2bSchema} uiSchema={ui} value={value} onChange={(next) => { value = next }} />)
  expect(screen.getByLabelText('内容 ID')).toBeInTheDocument()
})
