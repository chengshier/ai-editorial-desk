import { AdminApi } from './api'
import type {CitationUsage,DraftDetail,DraftGenerationResponse,DraftType,EditorialDraft,EditorialFormat,EditorialOverride,EditorialPack,EditorialRisk,EditorialScore,EffectiveEditorialResponse,EventCard,EventEvidence,EventQuery,EventUnknown,EvidenceClaim,EvidenceState,ScoreRunResponse,TrendSnapshot,WorkbenchEventDetail,WorkbenchEventPage,WorkbenchOverview,WorkbenchSignalPage} from './workbenchTypes'

const q=(params:Record<string,string|number|boolean|undefined>)=>{const s=new URLSearchParams();Object.entries(params).forEach(([k,v])=>{if(v!==undefined&&v!=='')s.set(k,String(v))});const v=s.toString();return v?`?${v}`:''}
const localToIso=(value:string|undefined)=>value?new Date(value).toISOString():undefined
export type DraftRefInput={claim_id:string;section_key:string;usage:CitationUsage}
export class WorkbenchApi{
 constructor(private readonly api:AdminApi){}
 overview(){return this.api.request<WorkbenchOverview>('/api/v1/admin/workbench/overview')}
 events(query:EventQuery){return this.api.request<WorkbenchEventPage>(`/api/v1/admin/workbench/events${q({page:query.page,page_size:query.pageSize,status:query.status,category:query.category,include_merged:query.includeMerged,risk:query.risk,has_evidence:query.hasEvidence,has_score:query.hasScore,has_draft:query.hasDraft,decision:query.decision,updated_from:localToIso(query.updatedFrom),updated_to:localToIso(query.updatedTo),q:query.q,sort_by:query.sortBy,sort_direction:query.sortDirection})}`)}
 event(id:string){return this.api.request<WorkbenchEventDetail>(`/api/v1/admin/workbench/events/${id}`)}
 signals(id:string,page=1,pageSize=50){return this.api.request<WorkbenchSignalPage>(`/api/v1/admin/workbench/events/${id}/signals${q({page,page_size:pageSize})}`)}
 evidence(id:string){return this.api.request<EventEvidence>(`/api/v1/admin/events/${id}/evidence`)}
 verifyClaim(eventId:string,claimId:string,state:EvidenceState,reason:string){return this.api.post<EvidenceClaim>(`/api/v1/admin/events/${eventId}/claims/${claimId}/verify`,{verification_state:state,reason})}
 updateClaimNote(eventId:string,claimId:string,editor_note:string){return this.api.patch<EvidenceClaim>(`/api/v1/admin/events/${eventId}/claims/${claimId}`,{editor_note})}
 attachClaimSource(eventId:string,claimId:string,signal_id:string,role:'supporting'|'contradicting'){return this.api.post<EvidenceClaim>(`/api/v1/admin/events/${eventId}/claims/${claimId}/sources`,{signal_id,role})}
 removeClaimSource(eventId:string,claimId:string,signalId:string){return this.api.delete(`/api/v1/admin/events/${eventId}/claims/${claimId}/sources/${signalId}`)}
 createUnknown(eventId:string,unknown_text:string){return this.api.post<EventUnknown>(`/api/v1/admin/events/${eventId}/unknowns`,{unknown_text})}
 updateUnknown(eventId:string,unknownId:string,status:'resolved'|'dismissed',resolution_note:string){return this.api.patch<EventUnknown>(`/api/v1/admin/events/${eventId}/unknowns/${unknownId}`,{status,resolution_note,resolved_by_claim_id:null})}
 merge(targetEventId:string,source_event_id:string,reason:string){return this.api.post(`/api/v1/admin/events/${targetEventId}/merge`,{source_event_id,reason})}
 split(eventId:string,signal_ids:string[],reason:string,title?:string){return this.api.post(`/api/v1/admin/events/${eventId}/split`,{signal_ids,reason,title:title||null})}
 calculateTrend(eventId:string,window_start_at:string,window_end_at:string){return this.api.post<{snapshot:TrendSnapshot;created:boolean}>(`/api/v1/admin/events/${eventId}/trend/calculate`,{window_start_at,window_end_at})}
 scores(eventId:string){return this.api.request<EditorialScore[]>(`/api/v1/admin/events/${eventId}/editorial-scores`)}
 effectiveScore(eventId:string){return this.api.request<EffectiveEditorialResponse>(`/api/v1/admin/events/${eventId}/editorial-scores/effective`)}
 previewScore(eventId:string,trend_snapshot_id:string){return this.api.post<ScoreRunResponse>(`/api/v1/admin/events/${eventId}/editorial-scores/preview`,{trend_snapshot_id})}
 applyScore(eventId:string,trend_snapshot_id:string){return this.api.post<ScoreRunResponse>(`/api/v1/admin/events/${eventId}/editorial-scores`,{trend_snapshot_id})}
 manualScore(eventId:string,payload:{trend_snapshot_id:string|null;emotion:number;information_gap:number;visual_value:number;user_relevance:number;discussion:number;novelty:number;extendability:number;risk_level:EditorialRisk;recommended_format:EditorialFormat;reason:string;model_reason?:string}){return this.api.post<EditorialScore>(`/api/v1/admin/events/${eventId}/editorial-scores/manual`,payload)}
 overrideScore(eventId:string,scoreId:string,payload:Record<string,unknown>&{reason:string}){return this.api.post<EditorialOverride>(`/api/v1/admin/events/${eventId}/editorial-scores/${scoreId}/override`,payload)}
 cards(eventId:string){return this.api.request<EventCard[]>(`/api/v1/admin/events/${eventId}/cards`)}
 createCard(eventId:string,trend_snapshot_id:string|null){return this.api.post<{card:EventCard;created:boolean}>(`/api/v1/admin/events/${eventId}/cards`,{trend_snapshot_id})}
 packs(eventId:string){return this.api.request<EditorialPack[]>(`/api/v1/admin/events/${eventId}/editorial-packs`)}
 createPack(eventId:string,event_card_id:string){return this.api.post<{pack:EditorialPack;created:boolean}>(`/api/v1/admin/events/${eventId}/editorial-packs`,{event_card_id})}
 drafts(eventId:string){return this.api.request<EditorialDraft[]>(`/api/v1/admin/events/${eventId}/drafts`)}
 draft(eventId:string,draftId:string){return this.api.request<DraftDetail>(`/api/v1/admin/events/${eventId}/drafts/${draftId}`)}
 previewDraft(eventId:string,p:{event_card_id:string;editorial_pack_id:string;draft_type:DraftType;risk_approval_reason?:string}){return this.api.post<DraftGenerationResponse>(`/api/v1/admin/events/${eventId}/drafts/preview`,p)}
 applyDraft(eventId:string,p:{event_card_id:string;editorial_pack_id:string;draft_type:DraftType;risk_approval_reason?:string}){return this.api.post<DraftGenerationResponse>(`/api/v1/admin/events/${eventId}/drafts`,p)}
 humanDraft(eventId:string,p:{event_card_id:string;editorial_pack_id:string;draft_type:DraftType;reason:string;body:string;references:DraftRefInput[];title?:string;hook?:string}){return this.api.post<EditorialDraft>(`/api/v1/admin/events/${eventId}/drafts/manual`,p)}
 revise(eventId:string,draftId:string,p:{change_note:string;body:string;references:DraftRefInput[];title?:string;hook?:string}){return this.api.post<EditorialDraft>(`/api/v1/admin/events/${eventId}/drafts/${draftId}/revisions`,p)}
 exportMarkdown(eventId:string,packId:string,draftId?:string){return this.api.text(`/api/v1/admin/events/${eventId}/editorial-pack/export.md${q({pack_id:packId,draft_id:draftId})}`)}
}
