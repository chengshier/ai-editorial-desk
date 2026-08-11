import {AdminApi,ApiError} from './api'
import type {ManualPerformanceInput,PerformanceImportPreview,PerformanceImportRun,PerformanceOverview,PerformanceTimelineItem,PublicationCreateInput,PublicationListResponse} from './publicationTypes'

const query=(values:Record<string,string|number|boolean|undefined>)=>{const p=new URLSearchParams();Object.entries(values).forEach(([k,v])=>{if(v!==undefined&&v!=='')p.set(k,String(v))});const s=p.toString();return s?`?${s}`:''}
export class PublicationApi{
 constructor(private readonly api:AdminApi){}
 publications(values:Record<string,string|number|boolean|undefined>={}){return this.api.request<PublicationListResponse>(`/api/v1/admin/publications${query(values)}`)}
 publication(id:string){return this.api.request(`/api/v1/admin/publications/${id}`)}
 record(input:PublicationCreateInput){return this.api.post<{publication:PublicationListResponse['items'][number]['publication'];reused:boolean}>('/api/v1/admin/publications',input)}
 timeline(id:string){return this.api.request<PerformanceTimelineItem[]>(`/api/v1/admin/publications/${id}/performance`)}
 manual(id:string,input:ManualPerformanceInput){return this.api.post(`/api/v1/admin/publications/${id}/performance`,input)}
 preview(csv_text:string){return this.api.post<PerformanceImportPreview>('/api/v1/admin/performance-imports/preview',{csv_text})}
 apply(csv_text:string,file_name:string){return this.api.post<{run:PerformanceImportRun;reused:boolean}>('/api/v1/admin/performance-imports',{csv_text,file_name,confirmation:true})}
 overview(values:Record<string,string|undefined>={}){return this.api.request<PerformanceOverview>(`/api/v1/admin/performance/overview${query(values)}`)}
 async publicationCounts():Promise<Record<string,number>>{const counts:Record<string,number>={};let page=1;while(true){const result=await this.publications({page,page_size:100});for(const item of result.items)counts[item.publication.event_id]=(counts[item.publication.event_id]||0)+1;if(page*result.page_size>=result.total)break;page+=1}return counts}
}
export function publicationError(error:unknown):string{return error instanceof ApiError?`${error.code}：${error.message}`:error instanceof Error?error.message:'发布或效果反馈发生未知错误'}
export const PERFORMANCE_CSV_HEADER='publication_id,platform_key,external_post_id,public_url,observed_at,horizon,views,completion_rate_percent,average_watch_seconds,likes,comments,shares,favorites,follower_delta'
