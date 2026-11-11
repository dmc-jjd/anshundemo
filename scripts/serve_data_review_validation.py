"""Isolated local UI harness. No production tasks or external model calls."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from app.storage import Store
from app.schemas import TaskState
from app.workflow import Dependencies
from app.event_analysis import negative_ranking
import app.main as main


def serve():
    store=Store(Path('data/ui-review-harness'));tid='manual-final-validation'
    records=[{'id':rid,'title':'模拟事件'+rid,'summary':'模拟网友反映服务事项'+rid,'sentiment':'负面','warning':'是','source':'模拟来源','published':'2026-10-01','source_ref':{}} for rid in ('a','b','c')]
    source=store.put_artifact(tid,'records',{'records':records})
    groups=[{'id':rid,'representative_id':rid,'title':'模拟事件'+rid,'member_ids':[rid]} for rid in ('a','b','c')]
    themes=[{'candidate_theme':'待人工分类','member_ids':['a','b','c']}]
    cases=[{'id':key,'source_id':a,'target_id':b,'source_evidence':[{'title':'模拟事件'+a,'summary':'模拟服务事项'+a}],
            'target_evidence':[{'title':'模拟事件'+b,'summary':'模拟服务事项'+b}],'reason':'模拟：模型无法确定是否同一事件'} for key,a,b in [('ab','a','b'),('ac','a','c')]]
    top10=[{**row,'rank':i+1,'status':'complete','summary':'模拟网友反映有关服务问题，要求相关单位核实处理。','source_refs':row['negative_ids']} for i,row in enumerate(negative_ranking(groups,records))]
    analysis=store.put_artifact(tid,'analysis',{'groups':groups,'theme_groups':themes,'all_record_ids':['a','b','c'],'merge_ambiguities':cases,
        'classification_issues':[{'event_id':g['id'],'member_ids':g['member_ids'],'reason':'模拟：需要人工分类'} for g in groups],
        'top10':top10,'pending_model':False,'counts':{}})
    local=store.put_artifact(tid,'local',{'groups':groups,'all_record_ids':['a','b','c'],'source_records_ref':source,'method':{'threshold':.65}})
    cluster=store.put_artifact(tid,'clusters',{'groups':themes})
    metrics=store.put_artifact(tid,'metrics',{'record_count':3,'sentiment':{'负面':3},'platform':{'模拟来源':3}})
    refs={'import_records':source,'filter_records:negative_or_warning':source,'filter_records:negative':source,'filter_records:warning':source,'group_events':local,
          'event_analysis':analysis,'cluster_event_themes':cluster,'calculate_metrics':metrics}
    state=TaskState(id=tid,kind='report',phase='awaiting_review',template_ref='anshun-monthly-colored',result_refs=refs,
        metadata={'simulation':True,'report_month':'2026-10','analysis_pending':False},
        review_items=[{'id':'review','kind':'data_review','status':'open','blocking':True,'allowed_actions':['confirm','modify','defer'],
        'details':{'event_ref':analysis,'analysis_ref':analysis,'cluster_ref':cluster,'metrics_ref':metrics}}])
    existing=next((t for t in store.list_tasks() if t.id==tid),None)
    store.put_task(state,existing.revision if existing else None)
    async def forbidden_model(role,payload):raise AssertionError('Model must never run after human review')
    main.store=store;main.deps=Dependencies(store,forbidden_model)
    uvicorn.run(main.app,host='127.0.0.1',port=8877,log_level='warning')


if __name__=='__main__':serve()
