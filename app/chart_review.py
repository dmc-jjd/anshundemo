"""Presentation-only human changes; no model invocation and no fact mutation."""
import asyncio,uuid
from .chart_spec import styles_for,definitions
from .frozen_report import FrozenReport
from .writer_tools import chart_payload
from .structured_writer import save_draft

async def update_report_charts(store,task_id,expected_hash,changes):
    state=store.get_task(task_id)
    if state.phase not in ('awaiting_final_review','facts_frozen'):raise ValueError('report_not_editable_in_current_phase')
    if not state.draft_ref:raise ValueError('draft_missing')
    draft=store.get_artifact(state.draft_ref)
    if draft['content_hash']!=expected_hash:raise ValueError('stale_draft_hash')
    template=store.get_artifact(state.template_ref);chosen=styles_for(template,{**state.metadata.get('chart_styles',{}),**changes})
    report=FrozenReport(store,task_id);charts={};allowed=set(draft['evidence_refs'])
    for spec in definitions(template):
        name=spec['id'];payload=await asyncio.to_thread(chart_payload,report,name,chosen[name])
        ref=store.put_artifact(task_id,'writer_chart',payload);charts[name]=ref;allowed.add(ref)
    latest=store.get_task(task_id)
    if latest.revision!=state.revision or latest.draft_ref!=state.draft_ref:raise ValueError('stale_draft_hash')
    latest.metadata['chart_styles']=chosen
    result=save_draft(store,latest,template,draft['slot_values'],allowed,charts,state.metadata.get('writer_issues',[]))
    from .reviewers import after_human_change
    after_human_change(store,task_id,expected_hash,[])
    store.append_event(task_id,{'type':'human_chart_styles','styles':chosen,'previous_hash':expected_hash,'draft_ref':result.draft_ref})
    return {'draft_ref':result.draft_ref,'styles':chosen,'fact_ref':result.fact_ref}
