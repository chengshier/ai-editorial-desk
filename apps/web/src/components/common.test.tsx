import { render,screen } from '@testing-library/react'
import { expect,it } from 'vitest'
import { Empty, ErrorBanner } from './common'

it('turns the browser fetch failure into an actionable Chinese error',()=>{
 render(<ErrorBanner error="Failed to fetch"/>)
 expect(screen.getByRole('alert')).toHaveTextContent('无法连接服务')
})

it('renders a structured empty state with a title and helper',()=>{
 render(<Empty text="当前还没有事件" helper="新的采集结果形成事件后会显示在这里。"/>)
 expect(screen.getByRole('status')).toHaveTextContent('当前还没有事件')
 expect(screen.getByRole('status')).toHaveTextContent('新的采集结果形成事件后会显示在这里。')
})
