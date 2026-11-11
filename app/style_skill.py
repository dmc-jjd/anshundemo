"""文风技能薄壳：客户注入点 + 既有公开名。加载/指纹/标签全部在 core/skills/registry.py。

待 S5：`is_second_section` 现在按「字段 id / kind / display_name」判断哪些字段算第二部分正文；
计划书 §6.1 要求改读 `template.fields[].skill_scope == 'second_section'`，但该字段尚未在
`template.json` 落地（S5 才填 fields/blocks），故本轮**行为保持不变**，只在此记明。
"""
import re
from core.skills import registry as _registry

LABELS=_registry.labels()
skill_context=_registry.skill_context
detector=_registry.detector

def is_second_section(field):
    """本文哪些字段算第二部分正文（客户语义，留在 app 层；S5 改读 field.skill_scope 后删除本函数）。"""
    return field['id'] in ('b40_analysis_paragraph','monthly_recommendations') or field.get('kind') in ('analysis','paragraph_list') or '研判分析' in field.get('display_name','')

def detect_style(store,task_id,draft,fields):
    docs=[];project=[]
    for field in fields:
        answer=draft.get('slot_values',{}).get(field['id'])
        if not answer or 'human_edit' in answer.get('source_refs',[]) or not is_second_section(field):continue
        value=answer['value'];text='\n\n'.join(value) if isinstance(value,list) else str(value)
        docs.append((field['id'],text))
        for match in re.finditer(r'(?:这一判断|这一分析|此判断)[^。！？\n]{0,160}(?:推演|高发认定|背景参考|背景材料)[^。！？\n]*[。！？]?',text):
            project.append({'field_id':field['id'],'kind':'meta_text','severity':'blocking','quote':match.group(),
                'description':'写作方法或证据免责声明混入正文。','suggestion':'把可核实资料自然融入论述，保留若、可能等判断限定；方法说明保留在审计材料中。','action':'revise','evidence_refs':[]})
    engine=detector();metrics=engine.measure_docs(docs);raw=engine.extract_candidates(docs)
    candidates=[]
    for kind in LABELS:
        for index,item in enumerate(raw.get(kind,[])):
            candidates.append({'candidate_id':f'{kind}:{index}','kind':kind,'allowed_labels':LABELS[kind],**item})
    packet={'draft_hash':draft['content_hash'],'skill':{k:v for k,v in skill_context().items() if k not in ('rules','semantic_criteria')},
        'metrics':metrics,'raw_semantic_candidates':raw,'semantic_candidates':candidates,'project_findings':project,'documents':dict(docs)}
    ref=store.put_artifact(task_id,'style_detection',packet)
    store.append_event(task_id,{'type':'style_detection','ref':ref,'draft_hash':draft['content_hash'],'candidates':len(candidates),'project_findings':len(project)})
    return ref,packet
