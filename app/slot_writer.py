"""Writer produces only named template values with record-level provenance."""
from __future__ import annotations
from .agent import get_prompt,prompt_profile
import json,re
from pathlib import Path
from pydantic import BaseModel,Field
from .config import ROOT
from .model_client import invoke_agent
from .tool_executor import RunContext
from .ooxml import read_docx
from .source_binding import SourceCatalog,NumberedSlot,invoke_numbered_writer,SourceBindingError

class SlotAnswer(BaseModel):
    slot_id:str
    value:str
    source_refs:list[str]=Field(default_factory=list)

TEXT_TYPES={'source_text','existing_field','theme_cluster','narrative_from_sources','computed_judgement'}
FIRST_BLOCKS={17,26,29,30}
WRITER_SLOT_IDS={'B17_GREEN_09','B26_YELLOW_24','B26_LIGHTGRAY_25',
                 'B29_MAGENTA_02','B29_YELLOW_03','B29_LIGHTGRAY_04',
                 'B30_RED_02','B30_RED_05','B30_YELLOW_06'}

def _issue(slot,error_type,message):
    return {'slot_id':slot['id'],'semantic':slot['semantic'],'error_type':error_type,'message':message}

async def write_first_section_slots(deps,task_id:str,result_refs:dict,only_slots:set[str]|None=None)->tuple[dict,list[dict]]:
    store=deps.store
    profile=prompt_profile(store.get_task(task_id).metadata)
    manifest=json.loads((ROOT/'templates/anshun-colored/report.template.json').read_text(encoding='utf-8'))
    slots=[x for x in manifest['placeholders'] if x['id'] in (only_slots or WRITER_SLOT_IDS)]
    template_blocks=read_docx(ROOT/'templates/anshun-colored/template-with-placeholders.docx')['blocks']
    template_paragraphs=[b['text'] for b in template_blocks if b['kind']=='paragraph']
    records=store.get_artifact(result_refs['import_records'])['records']
    by_id={r['id']:r for r in records}
    media=[r for r in records if r.get('media_level') in ('全国','省级') and r.get('title')]
    negative=[r for r in records if '负' in r.get('sentiment','') and r.get('title')]
    themes=store.get_artifact(result_refs['confirmed_theme_groups'])['groups'] if result_refs.get('confirmed_theme_groups') else []
    groups=store.get_artifact(result_refs['confirmed_event_groups'])['groups'] if result_refs.get('confirmed_event_groups') else []
    theme_of={mid:t['candidate_theme'] for t in themes for mid in t['member_ids']}
    values={}; issues=[]; ctx=RunContext(store,task_id,model_adapter=deps.model_adapter)
    for slot in slots:
        kind=slot['slot_type']
        # Year-over-year judgements need prior-year facts this system does not have;
        # skip the model call instead of letting it return an empty answer that fails validation.
        if kind=='computed_judgement':
            issues.append(_issue(slot,'missing_prior_year_data','缺去年同期同口径数据，按模板规则不生成同比判断，保留待人工填写。'))
            continue
        marker='{{'+slot['id']+'}}'
        paragraph=next((p for p in template_paragraphs if p.startswith(('（一）','（二）','（三）','（四）')) and marker in p),'')
        if not paragraph:
            issues.append(_issue(slot,'template_paragraph_missing','模板正文中未找到该槽位占位符。'))
            continue
        before,_,after=paragraph.partition(marker)
        instruction=get_prompt('writer.slot.base',profile)
        if kind=='theme_cluster':
            evidence=[{'ref':'theme:'+t['candidate_theme'],'theme':t['candidate_theme'],'record_count':len(t['member_ids']),
                       'sample_titles':[by_id[mid]['title'] for mid in t['member_ids'][:3] if mid in by_id]} for t in themes]
            if not evidence:
                issues.append(_issue(slot,'insufficient_evidence','缺少已确认的主题分组，无法生成主题名称，保留待人工填写。'))
                continue
            instruction+=get_prompt('writer.slot.themes',profile)
        elif kind=='narrative_from_sources':
            evidence=[{'ref':g['representative_id'],'event_id':g['id'],'theme':theme_of.get(g['representative_id'],''),
                       'title':g.get('title') or by_id[g['representative_id']]['title'],
                       'summary':by_id[g['representative_id']].get('summary','')[:400]}
                      for g in groups if g.get('representative_id') in by_id][:30]
            if not evidence:
                issues.append(_issue(slot,'insufficient_evidence','缺少已确认的事件及摘要，无法撰写概述，保留待人工填写。'))
                continue
            instruction+=get_prompt('writer.slot.narrative',profile)
        else:
            candidates=(media if slot['source_block_index'] in (17,26,29) else negative)[:12]
            evidence=[{'ref':r['id'],'title':r['title'],'source':r['source'],'category':r.get('category',''),
                       'published':r.get('published','')} for r in candidates]
            instruction+=get_prompt('writer.slot.titles',profile)
        try:
            allowed={x['ref'] for x in evidence};catalog=SourceCatalog(allowed)
            bound=await invoke_numbered_writer(catalog,{'instruction':instruction+'\n'+get_prompt('writer.source_binding',profile),'prompt_profile':profile,
                'slot':{'id':slot['id'],'semantic':slot['semantic'],'kind':kind,'required_source_fields':slot['source_fields_or_calculation'],
                        'available_evidence_fields':sorted(evidence[0]) if evidence else [],
                        'before_text':before[-90:],'after_text':after[:90]},
                'evidence':evidence},NumberedSlot,ctx)
            answer=SlotAnswer.model_validate(bound)
            # Empty value with empty refs is the agreed "insufficient evidence" answer:
            # record it as a missing slot, not as a validation failure.
            if answer.slot_id==slot['id'] and not answer.value.strip() and not answer.source_refs:
                issues.append(_issue(slot,'insufficient_evidence','模型判定现有证据不足以填写该槽位，保留待人工填写。'))
                continue
            if answer.slot_id!=slot['id'] or not answer.value.strip() or not answer.source_refs or not set(answer.source_refs)<=allowed or re.search(r'\{\{|\}\}',answer.value):
                raise ValueError('invalid_slot_answer')
            values[slot['id']]={'value':answer.value,'source_refs':answer.source_refs}
        except SourceBindingError as exc:
            issues.append({**_issue(slot,'writer_source_pending','正文已生成但引用待核对，候选正文已保留供最终人工确认。'),'candidate_value':exc.raw.get('value','')})
        except Exception as exc:
            issues.append(_issue(slot,type(exc).__name__,f'写作调用或校验未通过：{type(exc).__name__}，保留待人工填写。'))
        finally:catalog.audit(store,task_id,'legacy_slot_writer',[slot['id']])
    return values,issues
