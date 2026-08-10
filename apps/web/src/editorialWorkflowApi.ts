import { AdminApi,ApiError } from './api'
import type { CandidateApplyResponse,CandidateGenerationInput,CandidateGroup,CandidateListResponse,CandidatePreview,CandidateRun,DecisionHistoryItem,EditorialDecisionType,EventWorkflowSummary } from './editorialWorkflowTypes'
import type { EditorialRisk } from './workbenchTypes'

const query=(params:Record<string,string|number|undefined>)=>{const search=new URLSearchParams();Object.entries(params).forEach(([key,value])=>{if(value!==undefined&&value!=='')search.set(key,String(value))});const value=search.toString();return value?`?${value}`:''}
export class EditorialWorkflowApi{
 constructor(private readonly api:AdminApi){}
 runs(){return this.api.request<CandidateRun[]>('/api/v1/admin/editorial/candidate-runs?limit=50')}
 candidates(params:{runId?:string;topN:number;group?:CandidateGroup;risk?:EditorialRisk;category?:string}){const path=params.runId?`/api/v1/admin/editorial/candidate-runs/${params.runId}/candidates`:'/api/v1/admin/editorial/candidates';return this.api.request<CandidateListResponse>(`${path}${query({top_n:params.topN,candidate_group:params.group,risk:params.risk,category:params.category})}`)}
 preview(input:CandidateGenerationInput){return this.api.post<CandidatePreview>('/api/v1/admin/editorial/candidate-runs/preview',input)}
 apply(input:CandidateGenerationInput){return this.api.post<CandidateApplyResponse>('/api/v1/admin/editorial/candidate-runs',{...input,confirmation:true})}
 history(eventId:string){return this.api.request<DecisionHistoryItem[]>(`/api/v1/admin/editorial/events/${eventId}/decisions`)}
 summary(eventId:string){return this.api.request<EventWorkflowSummary>(`/api/v1/admin/editorial/events/${eventId}/workflow-summary`)}
 decide(eventId:string,payload:{candidate_id?:string|null;decision:EditorialDecisionType;expected_previous_decision_id?:string|null;risk_acknowledged:boolean;reason:string;confirmation:boolean}){return this.api.post<{decision:DecisionHistoryItem['decision'];reused:boolean}>(`/api/v1/admin/editorial/events/${eventId}/decision`,payload)}
}
export function editorialWorkflowError(error:unknown):string{if(!(error instanceof ApiError))return error instanceof Error?error.message:'Editorial workflow request failed';const labels:Record<string,string>={STALE_CANDIDATE_CONTEXT:'候选上下文已变化，请刷新或重新生成候选池。',EVENT_MERGED:error.targetEventId?`Event 已合并，请打开目标 Event ${error.targetEventId}。`:'Event 已合并，请刷新。',CANDIDATE_RUN_STALE:'当前候选来自旧 Run，只能只读，请切换到最新成功 Run。',EDITORIAL_DECISION_CONFLICT:'Editorial Decision 已被其他编辑更新，请刷新后重试。',RISK_ACKNOWLEDGEMENT_REQUIRED:'R3/R4 Adopt 必须明确勾选风险确认。'};return labels[error.code]||error.message}
