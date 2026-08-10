import type { EditorialFormat,EditorialRisk,EventStatus } from './workbenchTypes'

export type CandidateGroup='normal'|'review_required'
export type EditorialDecisionType='adopt'|'watch'|'drop'|'archive'
export interface CandidateRun{
 id:string;business_date:string;timezone:string;as_of_at:string;window_start_at:string;window_end_at:string;ranking_version:string;requested_limit:number;status:'succeeded'|'failed';input_hash:string;scanned_event_count:number;eligible_event_count:number;candidate_count:number;skipped_event_count:number;skip_summary:Record<string,number>;mode:'apply';actor:string;error_code:string|null;created_at:string;finished_at:string|null
}
export interface CandidateSnapshot{
 id:string|null;run_id:string|null;event_id:string;rank:number;candidate_group:CandidateGroup;event_title_snapshot:string;category_snapshot:string|null;event_status_snapshot:EventStatus;event_last_updated_at_snapshot:string;source_count_snapshot:number;platform_count_snapshot:number;trend_snapshot_id:string|null;base_editorial_score_id:string;effective_assessment_hash:string;effective_traffic_total:number;effective_risk_level:EditorialRisk;recommended_format:EditorialFormat;open_unknown_count:number;evidence_summary:Record<string,number>;ranking_components:Record<string,unknown>;card_exists_snapshot:boolean;draft_exists_snapshot:boolean;candidate_context_hash:string;created_at:string|null
}
export interface EditorialDecision{
 id:string;event_id:string;candidate_id:string|null;decision:EditorialDecisionType;previous_decision_id:string|null;candidate_context_hash:string|null;risk_acknowledged:boolean;risk_level_snapshot:EditorialRisk|null;effective_traffic_total_snapshot:number|null;reason:string;actor:string;created_at:string
}
export interface CandidateListItem{candidate:CandidateSnapshot;current_event_status:EventStatus|null;merged_into_event_id:string|null;current_editorial_decision:EditorialDecision|null;stale_indicator:boolean|null}
export interface CandidateListResponse{run:CandidateRun;items:CandidateListItem[];total:number;top_n:number}
export interface CandidatePreview{business_date:string;timezone:string;as_of_at:string;window_start_at:string;window_end_at:string;ranking_version:string;requested_limit:number;input_hash:string;scanned_event_count:number;eligible_event_count:number;candidate_count:number;skipped_event_count:number;skip_summary:Record<string,number>;candidates:CandidateSnapshot[]}
export interface CandidateApplyResponse{run:CandidateRun;candidates:CandidateSnapshot[];reused:boolean}
export interface DecisionHistoryItem{decision:EditorialDecision;candidate_rank:number|null;candidate_run_id:string|null;candidate_business_date:string|null;candidate_as_of_at:string|null}
export interface EventWorkflowSummary{current_editorial_decision:EditorialDecision|null;latest_candidate:CandidateSnapshot|null;latest_candidate_run:CandidateRun|null}
export interface CandidateGenerationInput{business_date?:string;timezone?:string;as_of_at?:string;lookback_hours:number;requested_limit:number;include_resolved?:boolean;include_archived?:boolean}
