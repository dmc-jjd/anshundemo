"""Classification remains reviewable when event deduplication is explicitly disabled."""
import asyncio

import pytest
from jsonschema import Draft202012Validator

import core.tool_executor as executor
from core.ports import ToolPolicy
from core.schemas import HumanDecision, TaskState, ToolCall, ToolResult
from core.storage import Store


@pytest.mark.parametrize('tool', ['classify_records', 'discover_topics'])
def test_classification_tools_declare_and_reject_missing_records_before_worker(tmp_path, monkeypatch, tool):
    store=Store(tmp_path)
    store.put_task(TaskState(id='t',kind='report',phase='processing',package='anshun_monthly'))
    ctx=executor.RunContext(store,'t',policy=ToolPolicy(allow=frozenset({tool})))
    runs=[]
    def worker(*args):
        runs.append(args)
        return ToolResult(status='error',error_code='KeyError')
    monkeypatch.setattr(executor,'_bounded_run',worker)
    result=asyncio.run(executor.execute_tool(ToolCall(call_id='invalid',tool_name=tool,arguments={}),ctx))
    assert result.error_code=='missing_required_argument'
    assert runs==[] and store.get_task('t').tool_calls==0
    schema=next(s.arguments_schema for s in executor._tool_specs() if s.name==tool)
    assert list(Draft202012Validator(schema).iter_errors({}))
    Draft202012Validator(schema).validate({'records_ref':'records-from-this-task'})


@pytest.mark.parametrize('tool', ['classify_records', 'discover_topics'])
def test_classification_tools_accept_authorized_records(tmp_path,monkeypatch,tool):
    from core.tools.records import classify_records
    from core.tools.events import discover_topics
    store=Store(tmp_path)
    store.put_task(TaskState(id='t',kind='report',phase='processing',package='anshun_monthly'))
    ref=store.put_artifact('t','records',{'records':[{'id':'a','category':''}]})
    ctx=executor.RunContext(store,'t',policy=ToolPolicy(allow=frozenset({tool})))
    handler={'classify_records':classify_records,'discover_topics':discover_topics}[tool]
    monkeypatch.setattr(executor,'_bounded_run',lambda name,args,*unused:handler(args,ctx))
    result=asyncio.run(executor.execute_tool(ToolCall(call_id='valid',tool_name=tool,
                                                   arguments={'records_ref':ref}),ctx))
    assert result.status=='needs_review' and not result.error_code
    assert store.get_task('t').result_refs[tool]==result.data_ref


def review_fixture(tmp_path):
    store=Store(tmp_path)
    source=store.put_artifact('t','records',{'records':[{'id':'a'},{'id':'b'},{'id':'c'}]})
    themes=[{'candidate_theme':'待人工分类','member_ids':['a','b']},
            {'candidate_theme':'教育管理','member_ids':['c']}]
    cluster=store.put_artifact('t','theme_clusters',{'groups':themes})
    state=TaskState(id='t',kind='report',phase='awaiting_review',package='anshun_monthly',
        metadata={'template_rules':{'features_source':'task_snapshot','features':{
            'dedup':False,'classification':True,'first_warning':False,'top10':False}}},
        result_refs={'filter_records:negative_or_warning':source,'cluster_event_themes':cluster},
        review_items=[{'id':'review','kind':'data_review','status':'open','allowed_actions':['confirm'],
                       'details':{'cluster_ref':cluster}}])
    store.put_task(state)
    return store,themes


@pytest.mark.parametrize('themes,error',[
    (None,'uncertain_classification_unresolved'),
    ([{'candidate_theme':'教育管理','member_ids':['a','c']}],'review_members_must_cover_records_once'),
    ([{'candidate_theme':'教育管理','member_ids':['a','a','b','c']}],'review_members_must_cover_records_once'),
    ([{'candidate_theme':'','member_ids':['a','b','c']}],'theme_name_required'),
])
def test_confirmation_checks_record_classification_without_event_analysis(tmp_path,themes,error):
    store,original=review_fixture(tmp_path)
    with pytest.raises(ValueError,match=error):
        store.apply_decision('t',HumanDecision(item_id='review',expected_revision=0,action='confirm',
                                            reason='test',payload={'groups':[],'themes':themes or original}))
    assert store.get_task('t').revision==0


def test_valid_record_classification_does_not_create_event_groups(tmp_path):
    store,_=review_fixture(tmp_path)
    themes=[{'candidate_theme':'社会民生','member_ids':['a','b']},{'candidate_theme':'教育管理','member_ids':['c']}]
    result=store.apply_decision('t',HumanDecision(item_id='review',expected_revision=0,action='confirm',
                                              reason='test',payload={'groups':[],'themes':themes}))
    assert store.get_artifact(result.result_refs['confirmed_event_groups'])['groups']==[]
    assert store.get_artifact(result.result_refs['confirmed_theme_groups'])['groups']==themes
