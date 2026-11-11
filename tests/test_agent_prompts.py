"""Prompt maintenance contract and routing, entirely offline."""
import ast,asyncio
from pathlib import Path
import pytest
from app.agent import AGENT_PROMPTS,REPORT_PROMPT_PROFILES,TEMPLATE_POLICY,get_prompt,prompt_profile,prompt_fingerprint
from app.structured_writer import write_structured_preview
from app.workflow import Dependencies
from test_frozen_writer import fixture


def test_monthly_outlook_prompts_share_research_and_output_quantity_policy():
    plan=get_prompt('historical_researcher.plan');research=get_prompt('historical_researcher.research')
    outlook=get_prompt('writer.outlook');field=get_prompt('writer.outlook_field');template=get_prompt('template_analyst.template')
    assert '5—8类' in plan and '5—8类' in research and '目标5类' in research
    assert '4—5类' in outlook and '4—5类' in field and '4—5类' in template
    policy=TEMPLATE_POLICY['recommendations']
    assert policy['min_items']==4 and policy['max_items']==5
    assert '5—8类' in policy['structure'] and '目标5类' in policy['structure'] and '4—5类' in policy['structure']


def test_history_research_failure_fallback_uses_current_outlook_quantity_policy():
    script=Path('app/static/insights.js').read_text(encoding='utf-8')
    assert '比较5—8类候选，目标5类合格选题' in script
    assert '输出4—5条月度工作建议' in script
    assert '比较至少4类候选' not in script and '选择3—4类未来风险' not in script


def test_instruction_literals_only_live_in_agent_registry():
    for path in Path('app').glob('*.py'):
        if path.name=='agent.py':continue
        tree=ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node,ast.Dict):
                for key,value in zip(node.keys,node.values):
                    if isinstance(key,ast.Constant) and key.value in ('instruction','execution_rule'):
                        assert not isinstance(value,ast.Constant),f'{path}:{value.lineno} has an inline prompt'
            if isinstance(node,ast.Name) and isinstance(node.ctx,ast.Load) and node.id.endswith(('_PROMPT','_INSTRUCTION')):
                pytest.fail(f'{path}:{node.lineno} reads a scattered prompt')

def test_report_profiles_inherit_explicitly_and_reject_unknown_configuration(monkeypatch):
    monkeypatch.setitem(REPORT_PROMPT_PROFILES,'other_monthly',{'writer.analysis':'另一份月报研判要求'})
    assert prompt_profile({}, {'metadata':{'writer_prompt_profile':'other_monthly'}})=='other_monthly'
    assert prompt_profile({'writer_prompt_profile':'anshun_monthly'}, {'metadata':{'writer_prompt_profile':'other_monthly'}})=='anshun_monthly'
    assert get_prompt('writer.analysis','other_monthly')=='另一份月报研判要求'
    assert get_prompt('writer.outlook','other_monthly')==AGENT_PROMPTS['writer.outlook']
    assert prompt_fingerprint('other_monthly')!=prompt_fingerprint()
    with pytest.raises(ValueError,match='unknown_writer_prompt_profile'):prompt_profile({'writer_prompt_profile':'typo'})
    with pytest.raises(KeyError,match='unknown_agent_prompt'):get_prompt('typo')

def test_actual_writer_routes_profile_and_preserves_human_text_when_profile_changes(tmp_path,monkeypatch):
    from app.writing_review import edit_structured
    store,template=fixture(tmp_path)
    monkeypatch.setitem(REPORT_PROMPT_PROFILES,'other_monthly',{'writer.general':'另一份月报的实际写作指令'})
    state=store.get_task('r');state.metadata['writer_prompt_profile']='other_monthly';store.put_task(state,state.revision)
    calls=[]
    async def model(role,payload):
        assert role=='writer'
        assert payload['instruction'].split('\n')[0] in ('另一份月报的实际写作指令','更新后的一般写作指令')
        assert get_prompt('writer.source_binding','other_monthly') in payload['instruction']
        assert payload['prompt_profile']=='other_monthly'
        calls.append(payload['remaining_fields'])
        return {'values':{key:{'value':'当前配置生成','source_refs':[payload['evidence'][0]['ref']]} for key in payload['remaining_fields']}}
    state=asyncio.run(write_structured_preview(Dependencies(store,model),'r'))
    fact=state.fact_ref
    assert len(calls)==2
    state=asyncio.run(write_structured_preview(Dependencies(store,model),'r'))
    assert len(calls)==2
    monkeypatch.setitem(REPORT_PROMPT_PROFILES,'other_monthly',{'writer.general':'另一份月报的实际写作指令','writer.outlook':'更新建议要求'})
    state=asyncio.run(write_structured_preview(Dependencies(store,model),'r'))
    assert len(calls)==2  # Outlook changes do not regenerate unrelated paragraphs.
    draft=store.get_artifact(state.draft_ref)
    edit_structured(store,'r',{'w1':'人工最终文本'},draft['content_hash'])
    monkeypatch.setitem(REPORT_PROMPT_PROFILES,'other_monthly',{'writer.general':'更新后的一般写作指令','writer.outlook':'更新建议要求'})
    state=asyncio.run(write_structured_preview(Dependencies(store,model),'r'))
    draft=store.get_artifact(state.draft_ref)
    assert calls[-1]==['w2'] and len(calls)==3
    assert draft['slot_values']['w1']['value']=='人工最终文本'
    assert 'human_edit' in draft['slot_values']['w1']['source_refs']
    assert state.fact_ref==fact


def test_outlook_prompt_leaves_deterministic_basis_and_research_to_program():
    prompt=get_prompt('writer.outlook');field=get_prompt('writer.outlook_field')
    assert '选择类别' in prompt and '依据性质由程序继承' in prompt
    assert 'basis_type必须与选题一致' not in prompt and 'basis_type标注依据性质' not in field
    assert '新资料不得自动加入原选题' in prompt and '新增依据必须重新研究' in prompt
