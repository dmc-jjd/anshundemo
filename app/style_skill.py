"""Pinned upstream detection and rule loading, with auditable project findings."""
import hashlib,importlib.util,json,re
from functools import lru_cache
from pathlib import Path
from .config import ROOT

SKILL_ROOT=ROOT/'skills/lieflat-less-ai-tone'
UPSTREAM='https://github.com/larashero3-dotcom/lieflat-less-ai-tone'
COMMIT='53160078a04926d98de57a233549612d1b89bdc9'
LABELS={
 'rename':['0组','1组','2组','3组及以上','无法判断'],
 'cohesion':['表面有连接词实际关系不清','明确承接','有关但转换突然','主题跳转缺少说明','无法判断'],
 'colon':['引语或人物发言','标题时间比例元数据或版式用途','定义或解释','空转提示','结论提示','其他正文冒号','无法判断'],
 'iso3':['高度同构','部分同构','只有词语重复句法不同','只有语义并列句法不同','无同构关系','无法判断'],
}

@lru_cache(maxsize=1)
def skill_context():
    text=(SKILL_ROOT/'SKILL.md').read_text(encoding='utf-8')
    criteria=(SKILL_ROOT/'references/semantic-criteria.md').read_text(encoding='utf-8')
    rules=text[text.index('## 改写原则'):]
    digest=hashlib.sha256((text+criteria+(SKILL_ROOT/'scripts/detect.py').read_text(encoding='utf-8')).encode()).hexdigest()
    return {'name':'lieflat-less-ai-tone','upstream':UPSTREAM,'commit':COMMIT,'sha256':digest,'rules':rules,'semantic_criteria':criteria}

@lru_cache(maxsize=1)
def detector():
    spec=importlib.util.spec_from_file_location('report_lieflat_detector',SKILL_ROOT/'scripts/detect.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def is_second_section(field):
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
