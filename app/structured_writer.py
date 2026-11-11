"""Fill a confirmed template using calculations and bounded frozen-data tools."""
from __future__ import annotations
from .agent import get_prompt,prompt_profile,prompt_fingerprint,DEFAULT_PROMPT_PROFILE
import copy,hashlib,uuid,zipfile
from pathlib import Path
from pydantic import BaseModel,Field,ValidationError
from .structured_template import load_confirmed_template,validate_values
from .config import DATA
from .model_client import invoke_agent
from .tool_executor import RunContext,execute_tool
from .schemas import DraftVersion,ToolCall
from .frozen_report import FrozenReport,Calculation,CALCULATION_CATALOG,query_materials
from .writer_tools import native_tools,CHARTS,HANDLERS
from .section_two import AnalysisPlan,OutlookItem,OutlookItemValidationError,role as second_role,policy_for,render_analysis,render_outlook_item,POLICY_VERSION
from .source_binding import SourceCatalog,NumberedAnswers,NumberedOutlookRepairAnswers,SourceBindingError,invoke_numbered_writer

class StructuredAnswers(BaseModel):
    values:dict[str,dict]=Field(default_factory=dict)
    analysis_plan:AnalysisPlan|None=None
    outlook_items:list[OutlookItem]|None=Field(default=None,min_length=4,max_length=5)
class StructuredOutlookRepairAnswers(StructuredAnswers):
    outlook_items:list[OutlookItem]|None=Field(default=None,min_length=1,max_length=5)
class CalculationPlans(BaseModel):
    calculations:dict[str,Calculation]=Field(default_factory=dict)

# Explicit definitions for the existing confirmed monthly template. New semantic
# fields use the same typed catalog through the planner, never guessed numbers.
KNOWN={
 'b5_issue_no':{'metric':'issue_number'},'b8_publish_month':{'metric':'publish_month'},'b8_publish_day':{'metric':'publish_day'},
 'b12_report_month':{'metric':'report_month'},'b26_month':{'metric':'report_month'},'b29_report_month':{'metric':'report_month'},
 'b17_total_volume':{'metric':'scaled_count'},'b17_peak_date':{'metric':'peak_date'},
 'b17_warning_count':{'metric':'count','scope':'confirmed_events'},'b17_warning_ratio':{'metric':'warning_percentage','scope':'confirmed_events'},
 'b17_top_negative_categories':{'metric':'category_names','scope':'confirmed_events'},
 'b26_platform_rank_list':{'metric':'platform_names'},'b26_platform_entries':{'metric':'platform_statistics'},'b26_key_platform_list':{'metric':'platform_names'},
 'b30_negative_total':{'metric':'count','scope':'confirmed_events'},'b30_top_category_with_share':{'metric':'leading_category','scope':'confirmed_events'},
 'b30_county_distribution_list':{'metric':'county_statistics','scope':'confirmed_events'},'b34_top10_table':{'metric':'top10'},
 'b26_main_channels':{'metric':'platform_names'},'b32_figure_no':{'metric':'constant','value':'4'},'b35_table_no':{'metric':'constant','value':'1'}}
for name,sentiment in [('positive','正面'),('neutral','中性'),('negative','负面')]:
    KNOWN['b17_'+name+'_count']={'metric':'sentiment_count','sentiment':sentiment}
    KNOWN['b17_'+name+'_ratio']={'metric':'sentiment_percentage','sentiment':sentiment}

def compact_field(field):
    return {k:field[k] for k in ('id','display_name','owner','kind','semantic','rule','format','binding') if k in field}

def field_prompt_fingerprint(field,profile):
    kind=second_role(field)
    prefixes=('writer.analysis',) if kind=='analysis' else ('writer.outlook','historical_researcher.') if kind=='outlook' else ('writer.general',)
    base=prompt_fingerprint(profile,prefixes)
    if kind:
        from .style_skill import skill_context
        base=hashlib.sha256((base+skill_context()['sha256']+get_prompt('style.application',profile)).encode()).hexdigest()
    return base

def calculation_for(field,report,plans):
    spec=plans.get(field['id']) or KNOWN.get(field['id'])
    if spec:
        spec=Calculation.model_validate(spec).model_dump()
        if field['id'] in ('b17_warning_count','b17_warning_ratio'):spec['scope']=report.warning_scope()
        return report.calculate(spec)
    binding=field.get('binding') or {}
    if binding.get('tool')=='top10_events':return report.calculate({'metric':'top10'})
    if binding.get('tool')=='calculate_metrics':
        value=report.metrics
        for part in binding['path']:value=value[part]
        return {'value':str(value),'source_refs':[report.fact_ref],'calculation':binding}
    raise ValueError('缺少计算定义；请指定该字段的统计口径。')

def data_values(template,report,plans=None):
    values={};issues=[]
    for field in template['fields']:
        if field['owner']!='data':continue
        try:
            result=calculation_for(field,report,plans or {})
            value={k:result[k] for k in ('value','source_refs')}
            validate_values(template,{field['id']:value},{report.fact_ref,report.state.metadata.get('report_parameters_ref')})
            values[field['id']]=value
        except Exception as exc:issues.append({'field_id':field['id'],'semantic':field.get('display_name',field['id']),'message':str(exc)[:600],'error':type(exc).__name__})
    return values,issues

def save_draft(store,state,template,values,allowed,charts,issues):
    missing=[f['id'] for f in template['fields'] if f['id'] not in values]
    issues=[i for i in issues if i.get('field_id') in missing or i.get('chart')]
    draft=DraftVersion(id=uuid.uuid4().hex,fact_ref=state.fact_ref,template_ref=state.template_ref,
        structured_template_ref=state.template_ref,slot_values=values,evidence_refs=sorted(allowed),chart_refs=charts,
        recommendations=values.get('monthly_recommendations',{}).get('value',[]),
        missing_recommendation_evidence=any(i.get('error')=='historical_evidence_insufficient' for i in issues))
    draft.content_hash=hashlib.sha256(draft.model_dump_json(exclude={'content_hash'}).encode()).hexdigest()
    state.draft_ref=store.put_artifact(state.id,'structured_draft',draft.model_dump())
    from lxml import etree as ET
    path=Path(template['layout_source'])
    if not path.exists() and (DATA/'uploads'/path.name).exists():path=DATA/'uploads'/path.name
    with zipfile.ZipFile(path) as z:expected=len(ET.fromstring(z.read('word/document.xml')).xpath('//*[local-name()="drawing"]'))
    pending=max(0,expected-len(charts))
    state.metadata.update(preview_only=bool(missing or pending),missing_fields=missing,writer_issues=issues,pending_charts=pending)
    state.metadata['structured_writer_version']=2
    store.put_task(state,state.revision)
    store.append_event(state.id,{'type':'structured_writer_result','template_ref':state.template_ref,'filled':list(values),'missing':missing,'issues':issues,'pending_charts':pending})
    return state

async def write_structured_preview(deps,task_id):
    store=deps.store;report=FrozenReport(store,task_id);state=report.state
    template=load_confirmed_template(store,state.template_ref);fields={f['id']:f for f in template['fields']}
    profile=prompt_profile(state.metadata,template)
    fingerprint=prompt_fingerprint(profile)
    previous_fingerprint=state.metadata.get('writer_prompt_fingerprint')
    same_prompts=previous_fingerprint==fingerprint if previous_fingerprint else profile==DEFAULT_PROMPT_PROFILE
    state.metadata['writer_tool_calls']=0
    store.put_task(state,state.revision)
    ctx=RunContext(store,task_id,phase='writing',model_adapter=deps.model_adapter,timeout=90)
    allowed={report.fact_ref};current_evidence_refs={report.fact_ref};charts={};plans={};plan_issues=[]
    catalog=SourceCatalog(allowed)
    if state.metadata.get('report_parameters_ref'):allowed.add(state.metadata['report_parameters_ref'])
    old=store.get_artifact(state.draft_ref) if state.draft_ref else {}
    same=old.get('fact_ref')==state.fact_ref and old.get('template_ref')==state.template_ref
    previous=old.get('slot_values',{}) if same else {}
    if same:allowed.update(old.get('evidence_refs',[]))
    unknown=[f for f in fields.values() if f['owner']=='data' and f['id'] not in KNOWN and not f.get('binding')]
    if unknown:
        errors=[]
        for attempt in range(3):
            try:
                answer=await invoke_agent('writer_data_planner',{'fields':[compact_field(f) for f in unknown],
                    'instruction':get_prompt('writer.data_planner',profile),
                    'catalog':CALCULATION_CATALOG,'calculation_schema':Calculation.model_json_schema(),
                    'frozen_context':report.summary(),'errors':errors},CalculationPlans,ctx)
                if set(answer.calculations)-{f['id'] for f in unknown}:raise ValueError('unknown_data_field')
                plans={key:spec.model_dump() for key,spec in answer.calculations.items()}
                errors=[]
                for field in unknown:
                    if field['id'] not in plans:errors.append(field['id']+':缺少计算定义');continue
                    try:
                        result=calculation_for(field,report,plans)
                        validate_values(template,{field['id']:{k:result[k] for k in ('value','source_refs')}},{report.fact_ref,state.metadata.get('report_parameters_ref')})
                    except Exception as exc:
                        from .frozen_report import MissingReportInput
                        if not isinstance(exc,MissingReportInput):errors.append(field['id']+':'+str(exc)[:600])
                if errors:continue
                break
            except Exception as exc:errors=[str(exc)[:1000]]
        if errors and not plans:plan_issues=[{'field_id':f['id'],'message':errors[-1]} for f in unknown]
    store.put_artifact(task_id,'writer_calculation_plan',{'template_ref':state.template_ref,'fact_ref':state.fact_ref,'calculations':{**KNOWN,**plans}})
    values,issues=data_values(template,report,plans);issues+=plan_issues
    for key,answer in previous.items():
        current_policy=key in fields and (not second_role(fields[key]) or state.metadata.get('writer_policy_versions',{}).get(key)==policy_for(fields[key]))
        old_fp=state.metadata.get('writer_field_prompt_fingerprints',{}).get(key)
        field_same=old_fp==field_prompt_fingerprint(fields[key],profile) if old_fp and key in fields else same_prompts or state.metadata.get('writer_prompt_profile_applied',DEFAULT_PROMPT_PROFILE)==profile
        if key in fields and fields[key]['owner']=='writer' and ('human_edit' in answer.get('source_refs',[]) or (field_same and state.metadata.get('structured_writer_version')==2 and current_policy)):
            try:validate_values(template,{key:answer},allowed,writer_only=True);values[key]=answer
            except Exception:pass
    history=None;history_ref=None;generated_policy={};pending_sources={}
    if any(second_role(f)=='outlook' and f['id'] not in values for f in fields.values()):
        from .historical_research import prepare_history
        history_ref,history=await prepare_history(report,ctx,profile=profile);allowed.add(history_ref)
        allowed.update(c['page_ref'] for t in history['topics'] for c in t['evidence'])
        allowed.update(t['knowledge_ref'] for t in history['topics'] if t.get('knowledge_ref'))

    async def writer_tool(name,args):
        if name not in HANDLERS:return {'error':'工具不在写作只读白名单内'}
        result=await execute_tool(ToolCall(call_id=uuid.uuid4().hex,tool_name=name,arguments=args,reason='结构化写作只读查询'),ctx)
        if result.status!='ok':return {'error':result.error_code,'message':result.warnings}
        allowed.add(result.data_ref);data=store.get_artifact(result.data_ref)
        if name=='query_frozen_materials':allowed.update(item['ref'] for item in data['items'])
        if name=='query_frozen_materials':current_evidence_refs.update(item['ref'] for item in data['items'])
        if name=='frozen_statistics':current_evidence_refs.add(result.data_ref)
        if name=='plot_frozen_chart':charts[data['chart_type']]=result.data_ref;data={k:v for k,v in data.items() if k!='png_base64'}
        return {'ref':result.data_ref,'result':data}

    async def numbered_tool(name,args):
        return catalog.project(await writer_tool(name,args))

    from lxml import etree as ET
    path=Path(template['layout_source'])
    if not path.exists() and (DATA/'uploads'/path.name).exists():path=DATA/'uploads'/path.name
    with zipfile.ZipFile(path) as z:expected=len(ET.fromstring(z.read('word/document.xml')).xpath('//*[local-name()="drawing"]'))
    for kind in CHARTS[:expected]:
        from .chart_spec import styles_for
        style=styles_for(template,state.metadata.get('chart_styles'))[kind]
        result=await writer_tool('plot_frozen_chart',{'chart_type':kind,'style':style})
        if result.get('error'):issues.append({'chart':kind,'message':str(result)})
    for block in template['blocks']:
        ids=list(dict.fromkeys(p['field'] for p in block['parts'] if p.get('field') in fields and fields[p['field']]['owner']=='writer' and p['field'] not in values))
        if not ids:continue
        section_role=next((second_role(fields[key]) for key in ids if second_role(fields[key])),None)
        if section_role=='outlook' and (not history or history['status']!='ready'):
            issues.extend({'field_id':key,'semantic':fields[key].get('display_name',key),'error':'historical_evidence_insufficient','message':'未来风险的候选比较或依据核对未完成；允许历史、季节和地方活动组合选题。'+('；'.join(history.get('errors',[]))[:900] if history else '')} for key in ids)
            continue
        negative=block['index'] in (30,40) or any(fields[k].get('kind')=='paragraph_list' for k in ids)
        query={'focus':'negative_events' if negative else 'media','limit':10}
        if section_role=='analysis':query['distinct_events']=True
        if not negative:query['sentiments']=['正面','中性']
        if block['index']==17:query.update(date=report.metrics.get('peak_day'))
        evidence=query_materials(report,query)
        if not evidence['items']:evidence=query_materials(report,{'focus':'all','limit':10,'date':query.get('date'),'sentiments':query.get('sentiments',[])})
        if not evidence['items']:evidence=query_materials(report,{'focus':'all','limit':10,'date':query.get('date')})
        allowed.update(x['ref'] for x in evidence['items'])
        current_evidence_refs.update(x['ref'] for x in evidence['items'])
        subset={**template['writer_schema'],'properties':{key:template['writer_schema']['properties'][key] for key in ids}}
        subset=copy.deepcopy(subset)
        subset.pop('required',None)
        if 'b40_analysis_paragraph' in ids:subset['properties']['b40_analysis_paragraph']['properties']['value'].update(minLength=300,maxLength=500)
        payload={'instruction':get_prompt('writer.general',profile),'prompt_profile':profile,
            'output_values_schema':subset,'template_parts':block['parts'],'template_rules':template.get('rules',{}),
            'report_context':report.summary(),'fields':[compact_field(fields[key]) for key in ids],
            'calculated_data_fields':{key:answer for key,answer in values.items() if fields[key]['owner']=='data'},
            'evidence':evidence['items']+[{'ref':report.fact_ref,'type':'confirmed_statistics','data':report.summary()}]}
        response_schema={'type':'object','additionalProperties':False,'properties':{'values':subset},'required':['values']}
        if section_role:
            from .style_skill import skill_context
            payload['skill']={**skill_context(),'application':get_prompt('style.application',profile)}
            complete_schema=NumberedAnswers.model_json_schema();response_schema['$defs']=complete_schema.get('$defs',{})
            plan_key='analysis_plan' if section_role=='analysis' else 'outlook_items'
            response_schema['properties']={plan_key:complete_schema['properties'][plan_key]};response_schema['required']=[plan_key]
            payload.pop('output_values_schema',None);payload.pop('calculated_data_fields',None)
            if section_role=='outlook':
                item_schema=response_schema['$defs']['NumberedOutlook']
                item_schema['properties']['paragraph']={'type':'string','minLength':180,'maxLength':600}
                item_schema['required']=list(dict.fromkeys(item_schema.get('required',[])+['paragraph']))
            else:
                plan_schema=response_schema['$defs']['NumberedAnalysis']
                plan_schema['properties']['paragraph']={'type':'string','minLength':300,'maxLength':500}
                plan_schema['required']=list(dict.fromkeys(plan_schema.get('required',[])+['paragraph']))
            payload['instruction']=get_prompt('writer.analysis',profile) if section_role=='analysis' else get_prompt('writer.outlook',profile)
            if section_role=='analysis':payload['instruction']+=get_prompt('writer.analysis_output',profile)
            if section_role=='analysis':payload['allowed_source_refs']=sorted(current_evidence_refs)
            payload['policy_version']=policy_for(fields[ids[0]])
            if section_role=='outlook' and history:
                payload['historical_research']={'window':history['window'],'topics':[{k:t.get(k) for k in ('category','basis_type','basis_label','frequency_supported','recurrence_supported','knowledge_basis','knowledge_ref','applies_to_months','evidence')} for t in history['topics']]}
                payload['report_context']={'report_month':report.parameters()['report_month'],'forecast_window':history['window']}
                payload['evidence']=[]
                payload['fields']=[{'id':key,'owner':'writer','execution_rule':get_prompt('writer.outlook_field',profile)} for key in ids]
        errors=[];reference_repair=None;candidate=None
        outlook_locked={};outlook_invalid=[];outlook_positions={};outlook_repair=None;final_outlook_items=None;dropped_outlook_items=[]
        def outlook_allowed_refs(category):
            topic=next((t for t in history['topics'] if t['category']==category),None) if history else None
            return sorted(({c['page_ref'] for c in topic['evidence']}|({topic['knowledge_ref']} if topic.get('knowledge_ref') else set())) if topic else set())
        def invalid_outlook(item,index,code,message,allowed_refs=None):
            return {'item_index':index,'category':item.category,'error_code':code,'message':message,
                    'item':item.model_dump(),'allowed_refs':outlook_allowed_refs(item.category) if allowed_refs is None else sorted(allowed_refs)}
        repair_response_schema=copy.deepcopy(response_schema) if section_role=='outlook' else None
        if repair_response_schema:repair_response_schema['properties']['outlook_items']['minItems']=1
        response_schema=catalog.schema(response_schema)
        if repair_response_schema:repair_response_schema=catalog.schema(repair_response_schema)
        payload=catalog.schema(payload)
        payload['instruction']+='\n'+get_prompt('writer.source_binding',profile)
        for attempt in range(3):
            remaining=[key for key in ids if key not in values]
            if not remaining:break
            store.append_event(task_id,{'type':'writer_block_start','block':block['index'],'field_count':len(remaining),'round':attempt+1})
            repairing_outlook=section_role=='outlook' and bool(outlook_positions)
            round_payload={**payload,'correction_errors':errors,'remaining_fields':remaining}
            if outlook_repair:round_payload['outlook_repair']=outlook_repair
            try:
                bound=await invoke_numbered_writer(catalog,round_payload,NumberedOutlookRepairAnswers if repairing_outlook else NumberedAnswers,ctx,
                    response_schema=repair_response_schema if repairing_outlook else response_schema,tools=native_tools(),tool_executor=numbered_tool,repair=reference_repair)
                answer=(StructuredOutlookRepairAnswers if repairing_outlook else StructuredAnswers).model_validate(bound);reference_repair=None;candidate=answer.model_dump()
                errors=[]
                if section_role=='analysis':
                    if not answer.analysis_plan:raise ValueError('必须提供两条有触发条件、升级路径、影响、信号与阻断措施的analysis_plan')
                    if not answer.analysis_plan.paragraph:raise ValueError('必须直接写analysis_plan.paragraph自然正文，chains仅供审计，不得依赖程序拼接成稿')
                    text,refs=render_analysis(answer.analysis_plan,current_evidence_refs)
                    answer.values={ids[0]:{'value':text,'source_refs':refs}}
                elif section_role=='outlook':
                    if not answer.outlook_items:raise ValueError('必须提供面向未来的outlook_items，不能改写本月TOP10')
                    answer.values={};valid_items=[];invalid_items=[]
                    if not repairing_outlook:outlook_positions={item.category:index for index,item in enumerate(answer.outlook_items)}
                    retry_categories={entry['category'] for entry in outlook_invalid}
                    topic_categories={t['category'] for t in history['topics']}
                    counts={category:sum(i.category==category for i in answer.outlook_items) for category in {i.category for i in answer.outlook_items}}
                    duplicates={category for category,count in counts.items() if count>1}
                    accepted={item.category for item in answer.outlook_items if item.category not in outlook_locked and (not repairing_outlook or item.category in retry_categories or item.category in topic_categories)}
                    outlook_invalid[:]=[entry for entry in outlook_invalid if entry['category'] not in accepted]
                    for index,item in enumerate(answer.outlook_items):
                        if item.category in outlook_locked or (repairing_outlook and item.category not in retry_categories and item.category not in topic_categories):continue
                        raw_item=item.model_copy(deep=True)
                        if item.category in duplicates:
                            invalid=invalid_outlook(raw_item,index,'duplicate_category','前瞻类别重复：'+item.category+'；每个类别只能保留一条。')
                        elif not item.paragraph:
                            invalid=invalid_outlook(raw_item,index,'missing_paragraph','每类风险必须提供自然完整的paragraph正文；不能省略正文后靠拼接审计字段成稿。')
                        else:
                            topic=next((t for t in history['topics'] if t['category']==item.category),None)
                            if topic:item.basis_type=topic.get('basis_type','historical')
                            try:
                                text,item_refs=render_outlook_item(item,history['topics'],history['window'])
                                outlook_locked[item.category]={'item_index':index,'position':outlook_positions.get(item.category,index),
                                    'category':item.category,'item':item.model_dump(),'text':text,'refs':item_refs}
                                outlook_invalid[:]=[entry for entry in outlook_invalid if entry['category']!=item.category]
                                continue
                            except OutlookItemValidationError as exc:
                                invalid=invalid_outlook(raw_item,index,exc.code,str(exc),exc.allowed_refs)
                        invalid_items.append(invalid);outlook_invalid.append(invalid)
                    valid_items=sorted(outlook_locked.values(),key=lambda entry:entry['position'])
                    if 4<=len(valid_items)<=5:
                        max_items=fields[ids[0]].get('value_schema',{}).get('maxItems')
                        if max_items and len(valid_items)>max_items:
                            dropped_outlook_items=[{'category':e['category'],'text':e['text'],'position':e['position']} for e in valid_items[max_items:]]
                            valid_items=valid_items[:max_items]
                        final_outlook_items=[OutlookItem.model_validate(entry['item']) for entry in valid_items]
                        rendered=[entry['text'] for entry in valid_items]
                        refs=sorted({ref for entry in valid_items for ref in entry['refs']})
                        answer.values={ids[0]:{'value':rendered,'source_refs':refs}};outlook_repair=None
                    else:
                        repair_items=[]
                        for entry in outlook_invalid:
                            numbers=[catalog.reverse[ref] for ref in entry['allowed_refs'] if ref in catalog.reverse]
                            message='前瞻类别和历史来源未对应；只能使用本类别允许资料编号。' if entry['error_code']=='category_source_mismatch' else entry['message']
                            repair_items.append({**entry,'message':message,'allowed_numbers':numbers})
                        outlook_repair={'invalid_items':repair_items}
                        errors=[entry['category']+'：'+entry['message']+'；允许资料编号：'+(','.join(map(str,entry['allowed_numbers'])) or '无') for entry in repair_items]
                        if not errors:errors=['前瞻合格类别不足4类；请仅补充或替换尚未合格的类别。']
                if set(answer.values)-set(ids):raise ValueError('unknown_or_protected_template_field')
                for key,value in answer.values.items():
                    try:
                        validate_values(template,{key:value},allowed,writer_only=True)
                        if key=='b40_analysis_paragraph' and not 300<=len(value['value'])<=500:raise ValueError(f'当前{len(value["value"])}字；必须300至500字。重写为约380字，仅列3项关键数字、2个风险和3项简短建议。不要罗列所有统计。')
                        values[key]=value
                        if section_role:
                            generated_policy[key]=policy_for(fields[key])
                            plan=answer.analysis_plan.model_dump() if section_role=='analysis' else [item.model_dump() for item in final_outlook_items]
                            allowed.add(store.put_artifact(task_id,'second_section_plan',{'field_id':key,'policy_version':policy_for(fields[key]),'plan':plan,'fact_ref':report.fact_ref,'historical_research_ref':history_ref,'dropped_items':dropped_outlook_items}))
                    except Exception as exc:errors.append(key+': '+str(exc)[:500])
                if section_role!='outlook':errors += [key+':未返回该字段，请补充只读查询并填写' for key in remaining if key not in values and key not in answer.values]
            except SourceBindingError as exc:
                reference_repair=exc;candidate=exc.raw;errors=[str(exc)]
                store.append_event(task_id,{'type':'writer_reference_pending','fields':remaining,'body_preserved':True,'round':attempt+1})
            except ValidationError as exc:errors=['.'.join(map(str,item['loc']))+': '+item['msg'] for item in exc.errors(include_input=False,include_url=False)]
            except Exception as exc:errors=[type(exc).__name__+': '+str(exc)[:1000]]
            finally:catalog.audit(store,task_id,'structured_writer',remaining)
            store.append_event(task_id,{'type':'writer_validation','block':block['index'],'round':attempt+1,'errors':errors})
        for key in ids:
            if key not in values:
                if section_role=='outlook':
                    valid_entries=sorted(outlook_locked.values(),key=lambda e:e['position'])
                    invalid_entries=list({e['category']:e for e in outlook_invalid}.values())
                    has_body=bool(valid_entries or invalid_entries)
                    source_only=bool(invalid_entries) and all(e.get('error_code')=='category_source_mismatch' for e in invalid_entries)
                    merged=[]
                    for e in valid_entries:
                        merged.append({'position':e['position'],'valid':True,'category':e['category'],'text':e['text'],'item':e['item'],'refs':e['refs']})
                    for e in invalid_entries:
                        merged.append({'position':e.get('item_index',0),'valid':False,'category':e['category'],'text':e['item'].get('paragraph') or e['item'].get('historical_basis',''),'item':e['item'],'refs':[]})
                    merged.sort(key=lambda x:(x['position'],0 if x['valid'] else 1))
                    value=[e['text'] for e in merged]
                    if has_body:
                        pending_sources[key]=store.put_artifact(task_id,'writer_pending_sources',{
                            'field_id':key,
                            'valid_items':[{'category':e['category'],'item':e['item'],'text':e['text'],'refs':e['refs'],'position':e['position']} for e in valid_entries],
                            'invalid_items':[{'item_index':e.get('item_index'),'category':e['category'],'item':e['item'],'error_code':e.get('error_code'),'message':e.get('message'),'allowed_refs':e.get('allowed_refs',[])} for e in invalid_entries],
                            'outlook_items':[{'category':e['category'],'text':e['text'],'valid':e['valid']} for e in merged],
                            'value':value,
                            'reason':'正文已生成，引用或校验未能在限定轮次内完成；候选正文与逐项错误已保留，供最终人工核对。',
                            'fact_ref':report.fact_ref,'template_ref':state.template_ref,
                            'status':'writer_source_pending' if source_only else 'writer_validation_pending'})
                    error='writer_unfilled' if not has_body else ('writer_source_pending' if source_only else 'writer_validation_pending')
                    issues.append({'field_id':key,'semantic':fields[key].get('display_name',key),
                        'message':('正文已生成，引用待核对；候选正文已保留，可在终稿人审确认。' if source_only else '正文已生成，部分校验未完成；候选正文已保留，可在终稿人审确认。') if has_body else '；'.join(errors)[:1800],
                        'error':error})
                    continue
                preview=None
                if candidate:
                    preview=(candidate.get('analysis_plan') or {}).get('paragraph') if section_role=='analysis' else [item.get('paragraph') for item in candidate.get('outlook_items') or []] if section_role=='outlook' else (candidate.get('values',{}).get(key) or {}).get('value')
                if preview:
                    from jsonschema import Draft202012Validator
                    if not Draft202012Validator(fields[key]['value_schema']).is_valid(preview):preview=None
                    if section_role=='analysis' and (not isinstance(preview,str) or len(preview)<300):preview=None
                    if section_role=='outlook' and (not isinstance(preview,list) or not 4<=len(preview)<=5 or any(not isinstance(text,str) or not 180<=len(text)<=600 for text in preview)):preview=None
                if preview:
                    pending_sources[key]=store.put_artifact(task_id,'writer_pending_sources',{'field_id':key,'value':preview,'reason':'正文已生成，引用未能在限定轮次内绑定；待最终人工核对。','fact_ref':report.fact_ref,'template_ref':state.template_ref,'status':'pending_sources'})
                issues.append({'field_id':key,'semantic':fields[key].get('display_name',key),'message':'正文已生成，引用待核对；候选正文已保留，可在终稿人审确认。' if preview else '；'.join(errors)[:1800],'error':'writer_source_pending' if preview else 'writer_unfilled'})
    state=store.get_task(task_id)
    state.metadata.setdefault('writer_policy_versions',{}).update(generated_policy)
    state.metadata['writer_prompt_profile_applied']=profile
    state.metadata['writer_prompt_fingerprint']=fingerprint
    state.metadata['writer_field_prompt_fingerprints']={key:field_prompt_fingerprint(fields[key],profile) for key in values if fields[key]['owner']=='writer'}
    state.metadata['writer_pending_sources']=pending_sources
    return save_draft(store,state,template,values,allowed,charts,issues)
