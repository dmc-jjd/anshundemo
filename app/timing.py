"""Persist phase boundaries; report wall time separately from human waiting."""
import copy
from datetime import datetime, timezone

HUMAN_PHASES={'awaiting_review','awaiting_template_confirmation','template_manual_review','awaiting_final_review','facts_frozen'}
RECOVERY_PHASES={'failed','template_review_failed','analysis_pending'}
TERMINAL_PHASES={'approved','cancelled','template_confirmed'}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def elapsed(start,end):
    return max(0,round((datetime.fromisoformat(end)-datetime.fromisoformat(start)).total_seconds()*1000))


def transition(state,previous=None,at=None):
    at=at or stamp()
    prior=previous.get('metadata',{}).get('timing') if previous else None
    timing=copy.deepcopy(prior) if prior else {'started_at':at,'partial_history':previous is not None,'segments':[]}
    segments=timing['segments']
    if not segments or segments[-1]['phase']!=state.phase:
        if segments:
            if segments[-1]['phase']=='paused' and state.phase!='paused':segments[-1]['ended_at']=at
            else:segments[-1].setdefault('ended_at',at)
        segments.append({'phase':state.phase,'started_at':at})
    if state.phase=='paused':segments[-1]['ended_at']=segments[-1]['started_at']
    if state.phase in TERMINAL_PHASES:
        segments[-1].setdefault('ended_at',at)
        timing.setdefault('ended_at',at)
    else:timing.pop('ended_at',None)
    state.metadata['timing']=timing


def snapshot(state,at=None):
    at=at or stamp();timing=state.metadata.get('timing')
    if not timing:return {'available':False,'server_time':at,'message':'此历史任务尚未记录阶段计时；继续处理后开始记录。'}
    effective_at=timing['segments'][-1].get('ended_at',at) if state.phase=='paused' else timing.get('ended_at',at)
    totals={'processing_ms':0,'human_wait_ms':0,'recovery_wait_ms':0,'paused_ms':0};stages={}
    for segment in timing['segments']:
        duration=elapsed(segment['started_at'],segment.get('ended_at',effective_at))
        phase=segment['phase'];stages[phase]=stages.get(phase,0)+duration
        kind='paused_ms' if phase=='paused' else 'human_wait_ms' if phase in HUMAN_PHASES else 'recovery_wait_ms' if phase in RECOVERY_PHASES else 'processing_ms'
        totals[kind]+=duration
    rounds=[]
    for key,batch in state.metadata.get('template_batches',{}).items():
        for entry in batch.get('archived_rounds',[])+batch.get('rounds',[]):
            rounds.append({**entry,'batch':key,'targets':batch['targets'],
                           'elapsed_ms':elapsed(entry['started_at'],entry.get('ended_at',at))})
    return {'available':True,'server_time':at,'started_at':timing['started_at'],'ended_at':timing.get('ended_at'),
            'partial_history':timing.get('partial_history',False),'total_ms':max(0,elapsed(timing['started_at'],effective_at)-totals['paused_ms']),
            **totals,'stages':[{'phase':phase,'elapsed_ms':duration} for phase,duration in stages.items()],
            'current_phase':state.phase,'current_bucket':'paused_ms' if state.phase=='paused' else 'human_wait_ms' if state.phase in HUMAN_PHASES else 'recovery_wait_ms' if state.phase in RECOVERY_PHASES else 'processing_ms',
            'rounds':rounds}
