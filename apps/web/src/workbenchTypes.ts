export type EventStatus='emerging'|'growing'|'stable'|'declining'|'resolved'
export type EventSignalRelation='origin'|'report'|'repost'|'reaction'|'official_response'|'correction'|'related'
export type EvidenceState='confirmed'|'investigating'|'single_source'|'disputed'|'false'
export type UnknownStatus='open'|'resolved'|'dismissed'
export type EditorialRisk='R0'|'R1'|'R2'|'R3'|'R4'
export type EditorialFormat='daily_compilation'|'quick_explainer'|'fact_check'|'deep_dive'|'entertainment'|'consumer_safety'
export type DraftType='short_30s'|'standard_90s'|'deep_180s'
export type DraftSource='ai'|'human'
export type CitationUsage='fact'|'attributed'|'disputed'|'debunked'

export interface EventView{
 id:string;title:string;summary:string|null;category:string|null;status:EventStatus;first_seen_at:string|null;last_updated_at:string;primary_language:string|null;entities:Array<Record<string,unknown>>;keywords:string[];source_count:number;platform_count:number;merged_into_event_id:string|null;created_at:string;updated_at:string
}
export interface TrendSnapshot{
 id:string;event_id:string;calculation_version:string;window_start_at:string;window_end_at:string;signal_count:number;new_signal_count:number;source_count:number;platform_count:number;signal_velocity:number|null;interaction_velocity:number|null;cross_source:boolean;cross_platform:boolean;semantic_novelty:number|null;cn_gap:number|null;update_value:number|null;feature_availability:Record<string,boolean>;component_metrics:Record<string,unknown>;input_hash:string;created_at:string
}
export interface EditorialScore{
 id:string;event_id:string;trend_snapshot_id:string|null;score_template:string;score_template_version:string;scoring_version:string;source_type:'ai'|'human';emotion:number;information_gap:number;visual_value:number;user_relevance:number;discussion:number;novelty:number;extendability:number;traffic_total:number;risk_level:EditorialRisk;recommended_format:EditorialFormat;model_reason:string|null;ai_invocation_id:string|null;scoring_run_id:string|null;input_hash:string;created_by_actor:string;source_reason:string|null;created_at:string
}
export interface EditorialOverride{id:string;editorial_score_id:string;overridden_fields:Record<string,unknown>;reason:string;actor:string;created_at:string}
export interface EffectiveEditorial{
 emotion:number;information_gap:number;visual_value:number;user_relevance:number;discussion:number;novelty:number;extendability:number;traffic_total:number;risk_level:EditorialRisk;recommended_format:EditorialFormat;model_reason:string|null;base_score_id:string;base_source_type:'ai'|'human'
}
export interface EffectiveEditorialResponse{event_id:string;latest_ai_score:EditorialScore|null;latest_human_score:EditorialScore|null;effective_base_score_id:string|null;effective_values:Record<string,unknown>|null;applied_overrides:EditorialOverride[]}
export interface EvidenceCounts{confirmed:number;investigating:number;single_source:number;disputed:number;false:number}
export interface EventCard{
 id:string;event_id:string;card_version:string;evidence_snapshot_hash:string;trend_snapshot_id:string|null;editorial_score_id:string;title:string;concise_summary:string;timeline:Array<Record<string,unknown>>;confirmed_claim_ids:string[];investigating_claim_ids:string[];single_source_claim_ids:string[];disputed_claim_ids:string[];false_claim_ids:string[];unknown_ids:string[];source_summary:Record<string,unknown>;effective_assessment:Record<string,unknown>;risk_level:EditorialRisk;recommended_format:EditorialFormat;generated_by:string;ai_invocation_id:string|null;input_hash:string;created_at:string
}
export interface EditorialPack{
 id:string;event_id:string;event_card_id:string;pack_version:string;recommended_format:EditorialFormat;suggested_angles:Array<Record<string,unknown>>;source_items:Array<Record<string,unknown>>;timeline_items:Array<Record<string,unknown>>;material_items:Array<Record<string,unknown>>;warnings:Array<Record<string,unknown>>;unknown_items:Array<Record<string,unknown>>;claim_references:Array<Record<string,unknown>>;input_hash:string;ai_invocation_id:string|null;created_at:string
}
export interface WorkbenchEventItem{
 event:EventView;latest_trend:TrendSnapshot|null;latest_ai_score:EditorialScore|null;latest_human_score:EditorialScore|null;effective_editorial:EffectiveEditorial|null;human_override_applied:boolean;applied_override_count:number;evidence_counts:EvidenceCounts;evidence_total:number;open_unknown_count:number;card_count:number;latest_card:EventCard|null;latest_card_id:string|null;latest_pack:EditorialPack|null;draft_count:number;latest_draft_id:string|null
}
export interface WorkbenchEventPage{items:WorkbenchEventItem[];page:number;page_size:number;total:number;has_next:boolean}
export interface WorkbenchEventDetail extends WorkbenchEventItem{signal_summary:{total:number;by_relation:Record<string,number>};draft_summary:{draft_count:number;chain_count:number;latest_draft_id:string|null}}
export interface WorkbenchSignal{event_signal_id:string;signal_id:string;relation:EventSignalRelation;confidence:number;attached_by:string;platform:string;source_id:string|null;source_name:string|null;source_type:string|null;author_name:string|null;published_at:string|null;collected_at:string;effective_at:string;title:string|null;original_url:string;canonical_url:string}
export interface WorkbenchSignalPage{items:WorkbenchSignal[];page:number;page_size:number;total:number;has_next:boolean}
export interface WorkbenchOverview{
 generated_at:string;active_event_count:number;lifecycle_counts:Record<EventStatus,number>;recent_new_event_count_24h:number;recent_updated_event_count_24h:number;events_with_evidence_count:number;open_unknown_count:number;high_risk_event_count:number;artifact_counts:{trend_snapshots:number;editorial_scores:number;event_cards:number;editorial_packs:number;drafts:number};collection_health:{failed_runs_24h:number;paused_risk_runs_24h:number;open_risk_events:number;paused_accounts:number;checkpoint_count:number};production_ai_provider_validation:'NOT_TESTED'
}
export interface EvidenceSource{signal_id:string;role:'supporting'|'contradicting';title:string|null;platform:string;author_name:string|null;published_at:string|null;collected_at:string;original_url:string;canonical_url:string}
export interface EvidenceClaim{id:string;event_id:string;claim_text:string;claim_type:'fact'|'allegation'|'opinion'|'forecast';verification_state:EvidenceState;extraction_confidence:number|null;claim_fingerprint:string;extraction_version:string;extraction_run_id:string|null;ai_invocation_id:string|null;created_by_type:'ai'|'human';created_by_actor:string|null;editor_note:string|null;created_at:string;updated_at:string;sources:EvidenceSource[]}
export interface EventUnknown{id:string;event_id:string;unknown_text:string;unknown_fingerprint:string;status:UnknownStatus;source_type:'ai'|'human';extraction_run_id:string|null;ai_invocation_id:string|null;resolved_by_claim_id:string|null;resolution_note:string|null;created_by_actor:string|null;created_at:string;updated_at:string}
export interface EventEvidence{event_id:string;claims:EvidenceClaim[];unknowns:EventUnknown[]}
export interface DraftReference{id:string;draft_id:string;claim_id:string;section_key:string;usage:CitationUsage;created_at:string}
export interface EditorialDraft{
 id:string;event_id:string;event_card_id:string;editorial_pack_id:string;draft_chain_id:string;draft_type:DraftType;format_key:EditorialFormat;duration_target_seconds:number;language:string;draft_version:number;parent_draft_id:string|null;source_type:DraftSource;status:'generated'|'edited'|'reviewed'|'archived';title:string|null;title_candidates:string[];hook:string|null;hook_candidates:string[];cover_text_candidates:string[];sections:Array<Record<string,unknown>>;body:string;ending:string|null;interaction_question:string|null;prompt_version:string|null;schema_version:string|null;ai_invocation_id:string|null;generation_run_id:string|null;input_hash:string;created_by_actor:string|null;change_note:string|null;created_at:string
}
export interface DraftDetail{draft:EditorialDraft;claim_references:DraftReference[];version_chain:EditorialDraft[]}
export interface DraftPreviewCandidate{draft_type:DraftType;format_key:EditorialFormat;title_candidates:string[];hook_candidates:string[];cover_text_candidates:string[];sections:Array<Record<string,unknown>>;ending:string|null;interaction_question:string|null}
export interface DraftGenerationResponse{run_id:string|null;ai_invocation_id:string|null;mode:'preview'|'apply';status:'running'|'succeeded'|'failed';draft:EditorialDraft|null;candidate:DraftPreviewCandidate|null;reused:boolean}
export interface ScoreRunResponse{run_id:string|null;ai_invocation_id:string|null;mode:'preview'|'apply';status:'running'|'succeeded'|'failed';score:EditorialScore|null;emotion:number;information_gap:number;visual_value:number;user_relevance:number;discussion:number;novelty:number;extendability:number;traffic_total:number;risk_level:EditorialRisk;recommended_format:EditorialFormat;model_reason:string;reused:boolean}
export interface EventQuery{page:number;pageSize:number;status?:EventStatus;category?:string;includeMerged?:boolean;risk?:EditorialRisk;hasEvidence?:boolean;hasScore?:boolean;hasDraft?:boolean;updatedFrom?:string;updatedTo?:string;q?:string;sortBy?:'last_updated_at'|'first_seen_at'|'traffic_total';sortDirection?:'asc'|'desc'}
