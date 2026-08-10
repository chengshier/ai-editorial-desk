import type { ReactNode } from 'react'
import { ApiError } from '../api'
import type { EditorialRisk,EventStatus,EvidenceState } from '../workbenchTypes'

export const fmt=(value:string|null|undefined)=>value?new Date(value).toLocaleString():'Unavailable'
export function Badge({children,tone='muted'}:{children:ReactNode;tone?:'muted'|'ok'|'warn'|'danger'|'info'}){return <span className={`badge wb-${tone}`}>{children}</span>}
export function EventBadge({value}:{value:EventStatus}){return <Badge tone={value==='resolved'?'muted':value==='growing'?'ok':'info'}>{value}</Badge>}
export function RiskBadge({value}:{value:EditorialRisk}){return <Badge tone={value==='R4'?'danger':value==='R3'?'warn':value==='R0'?'ok':'info'}>Risk {value}</Badge>}
export function EvidenceBadge({value}:{value:EvidenceState}){const tone=value==='confirmed'?'ok':value==='false'?'danger':value==='disputed'?'warn':value==='single_source'?'warn':'info';return <Badge tone={tone}>{value}</Badge>}
export function Metric({label,value,help}:{label:string;value:ReactNode;help?:string}){return <div className="metric"><small>{label}</small><strong>{value}</strong>{help&&<span>{help}</span>}</div>}
export function SectionState({loading,error,empty,children}:{loading:boolean;error:string|null;empty?:boolean;children:ReactNode}){if(loading)return <div className="section-state" role="status">Loading…</div>;if(error)return <div className="error-banner" role="alert">{error}</div>;if(empty)return <div className="empty">No data</div>;return <>{children}</>}
export function Unavailable({reason}:{reason?:string}){return <span className="unavailable">Unavailable{reason?` · ${reason}`:''}</span>}
export function safeUrl(value:string):string|null{try{const u=new URL(value);return u.protocol==='http:'||u.protocol==='https:'?u.toString():null}catch{return null}}
export function SafeLink({url,children}:{url:string;children?:ReactNode}){const safe=safeUrl(url);return safe?<a href={safe} target="_blank" rel="noopener noreferrer">{children||safe}</a>:<span className="unavailable">Unsafe URL blocked</span>}
export function FriendlyError(error:unknown):string{if(error instanceof ApiError){switch(error.code){case'STALE_EDITORIAL_CONTEXT':return'上下文已变化，请刷新后重新生成。';case'EVENT_MERGED':return'该 Event 已合并，不能创建新的业务 Artifact。';case'DRAFT_RISK_GATE_BLOCKED':return`Risk Gate 拒绝：${error.message}`;case'BUDGET_EXCEEDED':return`AI Budget exceeded：${error.message}`;case'ROUTE_DISABLED':return`AI route disabled：${error.message}`;case'PROVIDER_UNAVAILABLE':return`AI provider unavailable：${error.message}`;case'STRUCTURED_OUTPUT_INVALID':return`Structured output invalid：${error.message}`;default:return`${error.code}: ${error.message}`}}return error instanceof Error?error.message:'Unknown error'}
export function JsonSummary({value}:{value:unknown}){return <pre className="wb-json">{JSON.stringify(value,null,2)}</pre>}
