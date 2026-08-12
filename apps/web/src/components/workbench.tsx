import type { ReactNode } from 'react'
import { ApiError } from '../api'
import type { EditorialRisk,EventStatus,EvidenceState } from '../workbenchTypes'
import { eventStatusLabel } from '../uiLabels'

export const fmt=(value:string|null|undefined)=>value?new Date(value).toLocaleString():'暂无'
export function Badge({children,tone='muted'}:{children:ReactNode;tone?:'muted'|'ok'|'warn'|'danger'|'info'}){return <span className={`badge wb-${tone}`}>{children}</span>}
export function EventBadge({value}:{value:EventStatus}){return <Badge tone={value==='resolved'?'muted':value==='growing'?'ok':'info'}>{eventStatusLabel[value]||value}</Badge>}
export function RiskBadge({value}:{value:EditorialRisk}){return <Badge tone={value==='R4'||value==='R3'?'danger':value==='R2'?'warn':'ok'}>风险 {value}</Badge>}
export function EvidenceBadge({value}:{value:EvidenceState}){const tone=value==='confirmed'?'ok':value==='false'?'danger':value==='disputed'?'warn':value==='single_source'?'warn':'info';const labels:Record<string,string>={confirmed:'已确认',investigating:'核验中',single_source:'单一信源',disputed:'存在争议',false:'已证伪'};return <Badge tone={tone}>{labels[value]||value}</Badge>}
export function Metric({label,value,help,icon}:{label:string;value:ReactNode;help?:string;icon?:ReactNode}){return <div className={`metric ${icon?'with-icon':''}`}>{icon&&<span className="metric-icon" aria-hidden="true">{icon}</span>}<small>{label}</small><strong>{value}</strong>{help&&<span>{help}</span>}</div>}
export function SectionState({loading,error,empty,children}:{loading:boolean;error:string|null;empty?:boolean;children:ReactNode}){if(loading)return <div className="section-state" role="status">正在加载…</div>;if(error)return <div className="error-banner" role="alert">{error}</div>;if(empty)return <div className="empty">暂无数据</div>;return <>{children}</>}
export function Unavailable({reason}:{reason?:string}){return <span className="unavailable">暂无{reason?` · ${reason}`:''}</span>}
export function safeUrl(value:string):string|null{try{const u=new URL(value);return u.protocol==='http:'||u.protocol==='https:'?u.toString():null}catch{return null}}
export function SafeLink({url,children}:{url:string;children?:ReactNode}){const safe=safeUrl(url);return safe?<a href={safe} target="_blank" rel="noopener noreferrer">{children||safe}</a>:<span className="unavailable">已阻止不安全链接</span>}
export function FriendlyError(error:unknown):string{if(error instanceof ApiError){switch(error.code){case'STALE_EDITORIAL_CONTEXT':return'上下文已变化，请刷新后重新生成。';case'EVENT_MERGED':return'该 Event 已合并，不能创建新的业务 Artifact。';case'DRAFT_RISK_GATE_BLOCKED':return`Risk Gate 拒绝：${error.message}`;case'BUDGET_EXCEEDED':return`AI 预算已超限：${error.message}`;case'ROUTE_DISABLED':return`AI 路由已停用：${error.message}`;case'PROVIDER_UNAVAILABLE':return`AI 服务商不可用：${error.message}`;case'STRUCTURED_OUTPUT_INVALID':return`结构化输出无效：${error.message}`;default:return`${error.code}：${error.message}`}}return error instanceof Error?error.message:'发生未知错误'}
export function JsonSummary({value}:{value:unknown}){return <pre className="wb-json">{JSON.stringify(value,null,2)}</pre>}
