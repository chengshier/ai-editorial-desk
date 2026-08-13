import { render,screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi,it,expect } from 'vitest'
import { EditorialOverviewPage } from './EditorialOverviewPage'
import { AdminApi } from '../api'
import { WorkbenchApi } from '../workbenchApi'

it('shows the daily focus hero and takes editors to daily candidates',async()=>{
 const navigate=vi.fn()
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({
  generated_at:'2026-08-11T10:00:00Z',active_event_count:12,lifecycle_counts:{emerging:2,growing:3,stable:4,declining:2,resolved:1},recent_new_event_count_24h:3,recent_updated_event_count_24h:6,events_with_evidence_count:9,open_unknown_count:4,high_risk_event_count:2,
  artifact_counts:{trend_snapshots:1,editorial_scores:2,event_cards:3,editorial_packs:1,drafts:1},collection_health:{failed_runs_24h:0,paused_risk_runs_24h:0,open_risk_events:0,paused_accounts:0,checkpoint_count:3},production_ai_provider_validation:'NOT_TESTED',
  candidate_workflow:{business_date:'2026-08-11',timezone:'Asia/Shanghai',run_exists:true,latest_run:{candidate_count:20,as_of_at:'2026-08-11T10:00:00Z'},current_decision_counts:{adopt:2,watch:5,drop:1,archive:0}}
 })))
 const api=new WorkbenchApi(new AdminApi({apiBaseUrl:'http://api',adminToken:'token',actorId:'editor'}))
 render(<EditorialOverviewPage api={api} onNavigate={navigate}/>)
 expect(await screen.findByText('今日重点关注')).toBeInTheDocument()
 expect(screen.getByText(/20 条候选/)).toBeInTheDocument()
 await userEvent.click(screen.getByRole('button',{name:'进入今日候选'}))
 expect(navigate).toHaveBeenCalledWith('candidates')
})
