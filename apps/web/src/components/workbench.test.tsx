import { render,screen } from '@testing-library/react'
import { ApiError } from '../api'
import { FriendlyError,SafeLink } from './workbench'

it('blocks unsafe source URL schemes and allows safe external links',()=>{const{rerender}=render(<SafeLink url="javascript:alert(1)">unsafe</SafeLink>);expect(screen.getByText('已阻止不安全链接')).toBeInTheDocument();expect(screen.queryByRole('link')).toBeNull();rerender(<SafeLink url="https://example.com/source">safe</SafeLink>);const link=screen.getByRole('link',{name:'safe'});expect(link).toHaveAttribute('target','_blank');expect(link).toHaveAttribute('rel','noopener noreferrer')})

it('maps backend AI, stale and risk errors without inventing fallback semantics',()=>{expect(FriendlyError(new ApiError(409,'STALE_EDITORIAL_CONTEXT','stale'))).toMatch(/上下文已变化/);expect(FriendlyError(new ApiError(409,'DRAFT_RISK_GATE_BLOCKED','blocked'))).toMatch(/Risk Gate/);expect(FriendlyError(new ApiError(429,'BUDGET_EXCEEDED','daily'))).toMatch(/预算已超限/);expect(FriendlyError(new ApiError(503,'PROVIDER_UNAVAILABLE','offline'))).toMatch(/服务商不可用/);expect(FriendlyError(new ApiError(503,'ROUTE_DISABLED','disabled'))).toMatch(/路由已停用/);expect(FriendlyError(new ApiError(422,'STRUCTURED_OUTPUT_INVALID','bad json'))).toMatch(/结构化输出无效/)})
