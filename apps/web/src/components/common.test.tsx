import { render,screen } from '@testing-library/react'
import { expect,it } from 'vitest'
import { ErrorBanner } from './common'

it('turns the browser fetch failure into an actionable Chinese error',()=>{
 render(<ErrorBanner error="Failed to fetch"/>)
 expect(screen.getByRole('alert')).toHaveTextContent('无法连接服务')
})
