import type { Page } from './types'

export type SessionConfig={apiBaseUrl:string;adminToken:string;actorId:string}
const STORAGE_KEY='ai-editorial-m1-admin-session'
const defaultConfig=():SessionConfig=>({apiBaseUrl:import.meta.env.VITE_API_BASE_URL||'http://127.0.0.1:8000',adminToken:'',actorId:''})
export function loadSessionConfig():SessionConfig{const raw=sessionStorage.getItem(STORAGE_KEY);if(!raw)return defaultConfig();try{return{...defaultConfig(),...(JSON.parse(raw) as Partial<SessionConfig>)}}catch{return defaultConfig()}}
export function saveSessionConfig(config:SessionConfig):void{sessionStorage.setItem(STORAGE_KEY,JSON.stringify(config))}
export function clearSessionConfig():void{sessionStorage.removeItem(STORAGE_KEY)}

export class ApiError extends Error{
 constructor(public readonly status:number,public readonly code:string,message:string,public readonly targetEventId:string|null=null){super(message);this.name='ApiError'}
}
type ErrorEnvelope={error?:{code?:string;message?:string;details?:unknown};detail?:string|{message?:string}}

export class AdminApi{
 constructor(private readonly config:SessionConfig){}
 private async perform(path:string,init:RequestInit={}):Promise<Response>{
  const method=(init.method||'GET').toUpperCase();const headers=new Headers(init.headers);headers.set('Accept','application/json')
  if(init.body)headers.set('Content-Type','application/json')
  if(this.config.adminToken)headers.set('X-Admin-Token',this.config.adminToken)
  if(method!=='GET'&&method!=='HEAD'&&this.config.actorId)headers.set('X-Actor-ID',this.config.actorId)
  const response=await fetch(`${this.config.apiBaseUrl}${path}`,{...init,headers});if(response.ok)return response
  let message=`请求失败 (${response.status})`;let code=`HTTP_${response.status}`;let target:string|null=null
  try{
   const payload=await response.json() as ErrorEnvelope
   if(payload.error){message=payload.error.message||message;code=payload.error.code||code
    if(payload.error.details&&typeof payload.error.details==='object'){const details=payload.error.details as Record<string,unknown>;if(typeof details.ai_error_code==='string')code=details.ai_error_code;if(typeof details.message==='string'&&details.message)message=details.message;if(typeof details.target_event_id==='string')target=details.target_event_id}}
   else if(typeof payload.detail==='string')message=payload.detail;else if(payload.detail?.message)message=payload.detail.message
  }catch{/* Never log request headers, session config, or error response bodies. */}
  throw new ApiError(response.status,code,message,target)
 }
 async request<T>(path:string,init:RequestInit={}):Promise<T>{return(await this.perform(path,init)).json() as Promise<T>}
 async text(path:string,init:RequestInit={}):Promise<string>{return(await this.perform(path,init)).text()}
 page<T>(path:string):Promise<Page<T>>{return this.request<Page<T>>(path)}
 post<T>(path:string,body:unknown={}):Promise<T>{return this.request<T>(path,{method:'POST',body:JSON.stringify(body)})}
 patch<T>(path:string,body:unknown):Promise<T>{return this.request<T>(path,{method:'PATCH',body:JSON.stringify(body)})}
 async delete(path:string):Promise<void>{await this.perform(path,{method:'DELETE'})}
}
