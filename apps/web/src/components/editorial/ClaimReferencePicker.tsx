import { Badge } from '../workbench'
import type { CitationUsage,EvidenceClaim } from '../../workbenchTypes'
import { citationUsageLabel,evidenceStateLabel } from '../../uiLabels'

function usages(claim:EvidenceClaim):CitationUsage[]{
 switch(claim.verification_state){
  case'confirmed':return['fact','attributed']
  case'investigating':case'single_source':return['attributed']
  case'disputed':return['disputed']
  case'false':return['debunked']
 }
}
export function ClaimReferencePicker({claims,refs,onChange}:{claims:EvidenceClaim[];refs:Record<string,CitationUsage>;onChange:(next:Record<string,CitationUsage>)=>void}){
 return <div className="claim-picker">{claims.map(claim=>{const allowed=usages(claim),checked=Boolean(refs[claim.id]);return <label key={claim.id}><input type="checkbox" checked={checked} onChange={e=>{const next={...refs};if(e.target.checked)next[claim.id]=allowed[0];else delete next[claim.id];onChange(next)}}/><span><Badge tone={claim.verification_state==='confirmed'?'ok':claim.verification_state==='false'?'danger':'warn'}>{evidenceStateLabel[claim.verification_state]||claim.verification_state}</Badge> {claim.claim_text}</span>{checked&&<select aria-label={`引用方式 ${claim.id}`} value={refs[claim.id]} onChange={e=>onChange({...refs,[claim.id]:e.target.value as CitationUsage})}>{allowed.map(u=><option key={u} value={u}>{citationUsageLabel[u]||u}</option>)}</select>}</label>})}</div>
}
