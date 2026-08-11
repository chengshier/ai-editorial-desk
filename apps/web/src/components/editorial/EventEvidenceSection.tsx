import { useCallback,useEffect,useMemo,useState } from 'react'
import { Empty,Panel } from '../common'
import { Badge,EvidenceBadge,FriendlyError,SafeLink,SectionState,fmt } from '../workbench'
import type { WorkbenchApi } from '../../workbenchApi'
import type { EvidenceClaim,EvidenceState,EventEvidence,EventUnknown } from '../../workbenchTypes'
import { evidenceStateLabel,unknownStatusLabel } from '../../uiLabels'

const states:EvidenceState[]=['confirmed','investigating','single_source','disputed','false']
export function EventEvidenceSection({api,eventId,canWrite,onChanged}:{api:WorkbenchApi;eventId:string;canWrite:boolean;onChanged:()=>void}){
 const[data,setData]=useState<EventEvidence|null>(null);const[loading,setLoading]=useState(true);const[error,setError]=useState<string|null>(null);const[newUnknown,setNewUnknown]=useState('')
 const load=useCallback(async()=>{setLoading(true);setError(null);try{setData(await api.evidence(eventId))}catch(e){setError(FriendlyError(e))}finally{setLoading(false)}},[api,eventId])
 useEffect(()=>{void load()},[load])
 const mutate=async(fn:()=>Promise<unknown>)=>{try{setError(null);await fn();await load();onChanged()}catch(e){setError(FriendlyError(e))}}
 const grouped=useMemo(()=>Object.fromEntries(states.map(s=>[s,data?.claims.filter(c=>c.verification_state===s)||[]])) as Record<EvidenceState,EvidenceClaim[]>,[data])
 return <Panel title="证据、事实主张与待确认点" actions={<button onClick={()=>void load()}>刷新</button>}>
  <div className="notice">核验状态是最终权威。<strong>单一信源不等于已确认</strong>；待确认点是问题，不能作为事实展示。后端核验规则仍是最终门槛。</div>
  <SectionState loading={loading} error={error} empty={!data}>{data&&<>
   {states.map(state=><section className="claim-group" key={state}><h3><EvidenceBadge value={state}/> <span>{grouped[state].length}</span></h3>{grouped[state].length===0?<Empty text={`暂无${evidenceStateLabel[state]}的事实主张`}/>:grouped[state].map(claim=><ClaimCard key={claim.id} claim={claim} canWrite={canWrite} onVerify={(s,r)=>mutate(()=>api.verifyClaim(eventId,claim.id,s,r))} onNote={note=>mutate(()=>api.updateClaimNote(eventId,claim.id,note))} onAttach={(sid,role)=>mutate(()=>api.attachClaimSource(eventId,claim.id,sid,role))} onRemove={sid=>mutate(()=>api.removeClaimSource(eventId,claim.id,sid))}/>)}</section>)}
   <section className="unknown-group"><h3>待确认点</h3><div className="badges"><Badge tone="warn">待确认 {data.unknowns.filter(x=>x.status==='open').length}</Badge><Badge>已解决 {data.unknowns.filter(x=>x.status==='resolved').length}</Badge><Badge>已忽略 {data.unknowns.filter(x=>x.status==='dismissed').length}</Badge></div>
    <div className="unknown-list">{data.unknowns.map(u=><UnknownCard key={u.id} item={u} canWrite={canWrite} update={(status,note)=>mutate(()=>api.updateUnknown(eventId,u.id,status,note))}/>)}</div>
    <div className="inline-form"><label>新增人工待确认点<input value={newUnknown} onChange={e=>setNewUnknown(e.target.value)} placeholder="输入尚未解决的问题"/></label><button disabled={!canWrite||!newUnknown.trim()} title={!canWrite?'配置执行者 ID 后才能操作；已合并事件只读':''} onClick={()=>void mutate(async()=>{await api.createUnknown(eventId,newUnknown.trim());setNewUnknown('')})}>添加待确认点</button></div>
   </section>
  </>}</SectionState>
 </Panel>
}

function ClaimCard({claim,canWrite,onVerify,onNote,onAttach,onRemove}:{claim:EvidenceClaim;canWrite:boolean;onVerify:(s:EvidenceState,r:string)=>Promise<void>;onNote:(n:string)=>Promise<void>;onAttach:(id:string,role:'supporting'|'contradicting')=>Promise<void>;onRemove:(id:string)=>Promise<void>}){
 const[open,setOpen]=useState(false);const[state,setState]=useState<EvidenceState>(claim.verification_state);const[reason,setReason]=useState('');const[note,setNote]=useState(claim.editor_note||'');const[signalId,setSignalId]=useState('');const[role,setRole]=useState<'supporting'|'contradicting'>('supporting');const support=claim.sources.filter(s=>s.role==='supporting').length,against=claim.sources.filter(s=>s.role==='contradicting').length
 return <article className="claim-card"><div className="claim-head"><div><EvidenceBadge value={claim.verification_state}/> <Badge>{claim.claim_type}</Badge> <Badge tone={claim.created_by_type==='human'?'ok':'info'}>{claim.created_by_type==='human'?'人工':'AI'}</Badge></div><button aria-expanded={open} onClick={()=>setOpen(v=>!v)}>{open?'收起信源':'信源与操作'}</button></div><p className="claim-text">{claim.claim_text}</p><div className="claim-meta"><span>支持信源 {support}</span><span>反驳信源 {against}</span><span>置信度 {claim.extraction_confidence??'暂无'}</span><span>执行者 {claim.created_by_actor||'AI 来源'}</span><span>{fmt(claim.updated_at)}</span></div>{claim.editor_note&&<p className="editor-note">编辑备注：{claim.editor_note}</p>}
  {open&&<div className="claim-detail"><div className="source-columns"><div><h4>支持信源</h4>{claim.sources.filter(s=>s.role==='supporting').map(s=><SourceItem key={s.signal_id} source={s} canWrite={canWrite} remove={()=>onRemove(s.signal_id)}/>)}</div><div><h4>反驳信源</h4>{claim.sources.filter(s=>s.role==='contradicting').map(s=><SourceItem key={s.signal_id} source={s} canWrite={canWrite} remove={()=>onRemove(s.signal_id)}/>)}</div></div>
   <div className="inline-form"><label>核验状态<select value={state} onChange={e=>setState(e.target.value as EvidenceState)}>{states.map(v=><option key={v} value={v}>{evidenceStateLabel[v]}</option>)}</select></label><label>核验理由<input value={reason} onChange={e=>setReason(e.target.value)} placeholder="必填人工理由"/></label><button disabled={!canWrite||!reason.trim()} title={!canWrite?'配置执行者 ID 后才能操作；已合并事件只读':''} onClick={()=>void onVerify(state,reason)}>保存核验</button></div>
   <div className="inline-form"><label>编辑备注<input value={note} onChange={e=>setNote(e.target.value)}/></label><button disabled={!canWrite||!note.trim()} onClick={()=>void onNote(note)}>保存备注</button></div>
   <div className="inline-form"><label>信号 ID<input value={signalId} onChange={e=>setSignalId(e.target.value)} placeholder="已有原始信号 UUID"/></label><label>关系<select value={role} onChange={e=>setRole(e.target.value as 'supporting'|'contradicting')}><option value="supporting">支持</option><option value="contradicting">反驳</option></select></label><button disabled={!canWrite||!signalId.trim()} onClick={()=>void onAttach(signalId.trim(),role)}>关联信源</button></div>
  </div>}
 </article>
}
function SourceItem({source,canWrite,remove}:{source:EvidenceClaim['sources'][number];canWrite:boolean;remove:()=>Promise<void>}){return <div className="source-item"><SafeLink url={source.original_url}>{source.title||source.original_url}</SafeLink><small>{source.platform} · {source.author_name||'未知作者'} · {fmt(source.published_at||source.collected_at)}</small><button disabled={!canWrite} onClick={()=>void remove()}>移除</button></div>}
function UnknownCard({item,canWrite,update}:{item:EventUnknown;canWrite:boolean;update:(s:'resolved'|'dismissed',n:string)=>Promise<void>}){const[note,setNote]=useState(item.resolution_note||'');return <article className={`unknown-card ${item.status==='open'?'open':''}`}><div><Badge tone={item.status==='open'?'warn':'muted'}>{unknownStatusLabel[item.status]||item.status}</Badge> <Badge>{item.source_type==='human'?'人工':'AI'}</Badge></div><p>{item.unknown_text}</p>{item.resolution_note&&<small>处理说明：{item.resolution_note}</small>}{item.status==='open'&&<div className="inline-form"><label>处理说明<input value={note} onChange={e=>setNote(e.target.value)}/></label><button disabled={!canWrite||!note.trim()} onClick={()=>void update('resolved',note)}>标记已解决</button><button disabled={!canWrite||!note.trim()} onClick={()=>void update('dismissed',note)}>忽略</button></div>}</article>}
