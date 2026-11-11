from __future__ import annotations
import asyncio,hashlib,uuid
from datetime import date
from pathlib import Path
from fastapi import FastAPI,UploadFile,File,HTTPException,BackgroundTasks,Header
from fastapi.responses import HTMLResponse,FileResponse,Response,JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from .config import DATA,MODEL_URL,MODEL_NAME,MODEL_KEY
from .schemas import TaskState,HumanDecision,DraftVersion
from .storage import Store,ConflictError
from .workflow import Dependencies,run_report_graph,run_template_graph,freeze_facts,make_draft,make_preview_with_charts
from .export import export_docx
from .report_validation import validate_draft
from .api_views.data_review import apply_event_settings
from .api_views.template import apply_definition_patch,confirm_candidate
from .api_views.writing import apply_slot_values,assemble_review_view

store=Store(); deps=Dependencies(store)
app=FastAPI(title='安顺月报工作台 Demo')
app.mount('/static',StaticFiles(directory=Path(__file__).parent/'static'),name='static')
UPLOADS=DATA/'uploads'; UPLOADS.mkdir(exist_ok=True)

def get_task(task_id):
    try: return store.get_task(task_id)
    except KeyError: raise HTTPException(404,'task_not_found')
def conflict(e): raise HTTPException(409,str(e))

@app.get('/',response_class=HTMLResponse)
def index(): return (Path(__file__).parent/'static/index.html').read_text(encoding='utf-8')

@app.get('/api/status')
def status(): return {'model_configured':bool(MODEL_URL and MODEL_NAME and MODEL_KEY),'baseline_template_available':True,'baseline_template_reason':'8 月标色 Word 已核对并生成 99 个占位符；模板颜色与统计口径仍有待审项','sample_files':[x.name for x in Path.cwd().glob('*.docx')]+[x.name for x in Path.cwd().glob('*.xlsx')]}

@app.get('/api/workflow-graphs')
def workflow_graphs():
    from .workflow import build_report_graph,build_writing_graph
    result={}
    for name,compiled in [('report',build_report_graph(deps)),('writing',build_writing_graph(deps))]:
        graph=compiled.get_graph();result[name]={'nodes':list(graph.nodes),'edges':[{'source':e.source,'target':e.target,'conditional':e.conditional} for e in graph.edges],'mermaid':graph.draw_mermaid()}
    return result

@app.post('/api/files')
async def upload(file:UploadFile=File(...)):
    name=Path(file.filename or '').name
    if name!=file.filename or not name.lower().endswith(('.docx','.xlsx')): raise HTTPException(400,'invalid_filename_or_type')
    content=await file.read()
    if len(content)>100_000_000: raise HTTPException(413,'file_too_large')
    sha=hashlib.sha256(content).hexdigest(); fid=f'file-{sha[:20]}'
    dest=UPLOADS/f'{fid}{Path(name).suffix.lower()}'
    if not dest.exists(): dest.write_bytes(content)
    import zipfile
    readable=zipfile.is_zipfile(dest)
    return {'id':fid,'sha256':sha,'name':name,'readable':readable,'path':str(dest),'reason':None if readable else 'not_unencrypted_ooxml'}

@app.get('/api/templates')
def templates():
    items=[{'id':'anshun-monthly-colored','name':'安顺月报 · 五色逐项占位模板','version':1,'status':'candidate_requires_review','usable_for_final':False,'reason':'8 月标色 Word 已取得，颜色疑点与占位符口径待人工确认','manifest_url':'/api/template-manifest'}]
    for task in store.list_tasks():
        if task.kind=='template' and task.metadata.get('confirmed_template_ref') and not task.metadata.get('simulation'):
            try: artifact=store.get_artifact(task.metadata['confirmed_template_ref'])
            except (KeyError,FileNotFoundError,ValueError,OSError): continue
            if not artifact.get('writer_schema'): continue
            count=len(artifact.get('source_reports',[]))
            items.append({'id':task.metadata['confirmed_template_ref'],'name':f'{count} 份报告生成的结构化模板','version':1,'status':'confirmed_by_human','usable_for_final':False,'reason':'结构与 Schema 已确认；尚缺数据绑定的字段保留待填'})
    return items

@app.get('/api/template-manifest')
def template_manifest():
    import json
    return json.loads((Path(__file__).resolve().parents[1]/'templates/anshun-colored/report.template.json').read_text(encoding='utf-8'))

@app.get('/api/template-docx')
def template_docx():
    path=Path(__file__).resolve().parents[1]/'templates/anshun-colored/template-with-placeholders.docx'
    return FileResponse(path,media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',filename='安顺月报五色占位模板.docx')

class TaskCreate(BaseModel):
    file_ids:list[str]=Field(default_factory=list)
    paths:list[str]=Field(default_factory=list)
    template_ref:str=''
    report_month:str|None=None
    sheet_index:int=3
    mode:str='fallback'
    event_threshold:float|None=Field(default=None,gt=0,le=1)
    issue_number:int|None=Field(default=None,ge=1)
    publication_date:date|None=None

def _resolve_files(ids:list[str]):
    out=[]
    for fid in ids:
        paths=list(UPLOADS.glob(fid+'.*'))
        if not paths: raise HTTPException(404,f'file_not_found: {fid}')
        out.append(str(paths[0]))
    return out

@app.post('/api/template-tasks')
async def template_task(req:TaskCreate,background_tasks:BackgroundTasks,idempotency_key:str|None=Header(None)):
    paths=_resolve_files(req.file_ids)
    if len(paths)<2: raise HTTPException(422,'at_least_two_uploaded_reports_required')
    if any(not path.lower().endswith('.docx') for path in paths):raise HTTPException(422,'docx_reports_required')
    if len({hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths})!=len(paths):
        raise HTTPException(422,'duplicate_reports')
    task_id=uuid.uuid4().hex
    if idempotency_key:
        existing=store.idempotent('template:'+idempotency_key,task_id)
        if existing!=task_id: return store.get_task(existing)
    state=TaskState(id=task_id,kind='template',phase='queued',input_refs=req.file_ids,metadata={'paths':paths})
    store.put_task(state); background_tasks.add_task(run_template_graph,deps,task_id)
    return state

@app.post('/api/report-tasks')
async def report_task(req:TaskCreate,background_tasks:BackgroundTasks,idempotency_key:str|None=Header(None)):
    paths=_resolve_files(req.file_ids)
    if len(paths)!=1 or not paths[0].lower().endswith('.xlsx'): raise HTTPException(422,'one_xlsx_required')
    rules={}
    if req.template_ref!='anshun-monthly-colored':
        from .structured_template import load_confirmed_template
        try: rules=load_confirmed_template(store,req.template_ref).get('rules',{})
        except (KeyError,ValueError): raise HTTPException(409,'confirmed_two_report_template_required')
    task_id=uuid.uuid4().hex
    if idempotency_key:
        existing=store.idempotent('report:'+idempotency_key,task_id)
        if existing!=task_id: return store.get_task(existing)
    state=TaskState(id=task_id,kind='report',phase='queued',template_ref=req.template_ref,input_refs=req.file_ids,metadata={'input_path':paths[0],'report_month':req.report_month,'sheet_index':req.sheet_index,'mode':req.mode,'event_scope':'negative_or_warning','event_scope_confirmed':True,'event_scope_applies_to':'first_section_four_categories_districts_top10','event_scope_authority':'user_confirmed_2026_11_06','template_rules':rules,'event_threshold':req.event_threshold or rules.get('event_threshold',.65)})
    parameters={key:value for key,value in req.model_dump(mode='json').items() if key in ('issue_number','publication_date') and value is not None}
    if parameters:
        state.metadata['report_parameters']=parameters
        state.metadata['report_parameters_ref']=store.put_artifact(task_id,'report_parameters',{'parameters':parameters,'source':'report_processing_form'})
    store.put_task(state); background_tasks.add_task(run_report_graph,deps,task_id)
    return state

@app.get('/api/report-parameter-suggestions')
def report_parameter_suggestions(template_ref:str,report_month:str):
    from .report_parameters import suggestions
    from .structured_template import load_confirmed_template
    try:
        template={} if template_ref=='anshun-monthly-colored' else load_confirmed_template(store,template_ref)
        return suggestions(template,report_month)
    except (ValueError,KeyError) as exc:raise HTTPException(422,str(exc))

@app.get('/api/tasks')
def tasks():
    return [{'id':task.id,'kind':task.kind,'phase':task.phase,'revision':task.revision,'created_at':task.created_at,
             'metadata':{'simulation':task.metadata.get('simulation',False)}} for task in store.list_tasks()]
@app.get('/api/tasks/{task_id}')
def task(task_id:str): return get_task(task_id)
@app.get('/api/tasks/{task_id}/events')
def events(task_id:str,after:int=0,limit:int=20): get_task(task_id); return store.events(task_id,after,limit)

@app.get('/api/tasks/{task_id}/timing')
def task_timing(task_id:str):
    from .timing import snapshot
    return snapshot(get_task(task_id))

@app.get('/api/tasks/{task_id}/usage')
def task_token_usage(task_id:str):
    from .usage import task_usage
    get_task(task_id)
    return task_usage(store,task_id)

@app.get('/api/tasks/{task_id}/reference-comparison')
def reference_comparison(task_id:str,details:bool=False):
    from .reference_comparison import view
    get_task(task_id)
    try:return view(store,task_id,details)
    except ValueError as exc:raise HTTPException(404,str(exc))

@app.get('/api/tasks/{task_id}/historical-research')
def historical_research_view(task_id:str):
    from .historical_web import page_read_error
    state=get_task(task_id);ref=state.metadata.get('historical_research_ref')
    if not ref:raise HTTPException(404,'historical_research_not_ready')
    data=store.get_artifact(ref)
    for topic in data['topics']:
        for citation in topic['evidence']:
            page=store.get_artifact(citation['page_ref'])
            citation.update(url=page['url'],title=page['title'],published_at=page.get('published_at'))
    events=store.events(task_id)
    counts={kind:sum(e['type']=='web_usage' and e.get('operation')==kind and e.get('billable',False) for e in events) for kind in ('search','fetch')}
    pages=[];skipped={item['url']:item for item in state.metadata.get('historical_reader',{}).get('failed_urls',{}).values()}
    for page_ref in data.get('source_refs',[]):
        if page_ref.startswith('historical_page-') and store.artifact_belongs_to_task(page_ref,task_id):
            page=store.get_artifact(page_ref)
            error=page_read_error(page.get('content',''))
            if error:skipped[page['url']]={'url':page['url'],'reason':error}
            else:pages.append({k:page.get(k) for k in ('url','title','published_at')})
    return {'ref':ref,**data,'web_summary':counts,'read_pages':pages,'skipped_pages':list(skipped.values())}

@app.get('/api/token-pricing')
def get_token_pricing():
    from .usage import configuration
    return configuration(store)

@app.put('/api/token-pricing')
def update_token_pricing(req:dict):
    from .usage import save_configuration
    try:return save_configuration(store,req)
    except ValueError as exc:raise HTTPException(422,str(exc))

class DecisionRequest(BaseModel):
    item_id:str
    expected_revision:int
    action:str
    payload:dict=Field(default_factory=dict)
    reason:str

@app.post('/api/tasks/{task_id}/decisions')
def decision(task_id:str,req:DecisionRequest):
    get_task(task_id)
    try: return store.apply_decision(task_id,HumanDecision(**req.model_dump()))
    except (ConflictError,ValueError) as e: conflict(e)
    except KeyError: raise HTTPException(404,'item_not_found')

@app.post('/api/tasks/{task_id}/confirm-facts')
def confirm_facts(task_id:str):
    try: return freeze_facts(deps,task_id)
    except ValueError as e: raise HTTPException(409,str(e))

class DataConfirmation(BaseModel):
    expected_revision:int
    groups:list[dict]
    themes:list[dict]
    merge_decisions:dict[str,str]=Field(default_factory=dict)
    briefs:dict[str,dict]=Field(default_factory=dict)

@app.post('/api/tasks/{task_id}/confirm-data')
def confirm_data(task_id:str,req:DataConfirmation):
    state=get_task(task_id)
    if state.fact_ref or state.phase!='awaiting_review':raise HTTPException(409,'invalid_data_review_stage')
    item=next((x for x in state.review_items if x['kind']=='data_review' and x['status']=='open'),None)
    if not item:raise HTTPException(409,'data_review_required')
    try:
        store.apply_decision(task_id,HumanDecision(item_id=item['id'],expected_revision=req.expected_revision,
            action='confirm',payload={'groups':req.groups,'themes':req.themes,'merge_decisions':req.merge_decisions,'briefs':req.briefs},reason='已在数据审核页查看并确认本期统计、事件和分类'))
        return freeze_facts(deps,task_id)
    except (ValueError,ConflictError) as exc:raise HTTPException(409,str(exc))

async def generate_draft(task_id,review_only=False):
    try:
        if review_only:
            from .workflow import run_writing_graph
            await run_writing_graph(deps,task_id,review_only=True)
        else:await make_preview_with_charts(deps,task_id)
    except Exception as exc:
        state=get_task(task_id);state.phase='facts_frozen'
        state.metadata['writing_error']='写作未完成，请重试或查看日志。'
        store.put_task(state,state.revision)
        store.append_event(task_id,{'type':'writing_failed','error_type':type(exc).__name__})

@app.post('/api/tasks/{task_id}/preview-draft')
async def preview_draft(task_id:str,background_tasks:BackgroundTasks):
    state=get_task(task_id)
    if not state.fact_ref:raise HTTPException(409,'data_review_required')
    from .reviewers import ACTIVE_PHASES
    if state.phase in ACTIVE_PHASES:raise HTTPException(409,'writing_in_progress')
    if state.phase not in ('facts_frozen','awaiting_final_review'):raise HTTPException(409,'invalid_writing_stage')
    state.phase='writing';state.metadata.pop('writing_error',None);store.put_task(state,state.revision)
    background_tasks.add_task(generate_draft,task_id)
    return state

class DraftReviewRequest(BaseModel):
    expected_hash:str

@app.post('/api/tasks/{task_id}/review-draft')
async def review_current_draft(task_id:str,req:DraftReviewRequest,background_tasks:BackgroundTasks):
    state=get_task(task_id)
    if state.phase not in ('awaiting_final_review','facts_frozen') or not state.draft_ref:raise HTTPException(409,'invalid_writing_stage')
    if store.get_artifact(state.draft_ref)['content_hash']!=req.expected_hash:raise HTTPException(409,'stale_draft_hash')
    state.phase='writing';store.put_task(state,state.revision);background_tasks.add_task(generate_draft,task_id,True)
    return state

class ManualWritingReview(BaseModel):
    expected_hash:str
    issue_ids:list[str]
    reason:str=''

@app.post('/api/tasks/{task_id}/writing-review/resolve')
def resolve_writing_review(task_id:str,req:ManualWritingReview):
    from .reviewers import resolve_human_review
    try:return resolve_human_review(store,task_id,req.expected_hash,req.issue_ids,req.reason)
    except (ValueError,KeyError) as exc:raise HTTPException(409,str(exc))

class ReviewExcerptLocation(BaseModel):
    paragraph_index:int|None=None
    start:int=Field(ge=0)
    end:int=Field(ge=1)

class ReviewExcerptEdit(BaseModel):
    expected_hash:str
    replacement:str
    location:ReviewExcerptLocation|None=None

@app.post('/api/tasks/{task_id}/writing-review/{issue_id}/edit')
def edit_writing_review_excerpt(task_id:str,issue_id:str,req:ReviewExcerptEdit):
    from .writing_review import edit_review_excerpt
    try:return edit_review_excerpt(store,task_id,issue_id,req.expected_hash,req.replacement,req.location.model_dump() if req.location else None)
    except (ValueError,KeyError) as exc:raise HTTPException(409,str(exc))

@app.get('/api/tasks/{task_id}/writing-review')
def writing_review_view(task_id:str):
    state=get_task(task_id)
    if not state.draft_ref:raise HTTPException(409,'draft_missing')
    return assemble_review_view(store,state)

@app.post('/api/tasks/{task_id}/pause')
def pause(task_id:str):
    state=get_task(task_id)
    if state.phase in ('approved','cancelled','template_confirmed'):raise HTTPException(409,'terminal_task_cannot_be_paused')
    if state.phase=='paused':return state
    from .timing import stamp
    state.metadata['paused_from_phase']=state.phase
    state.metadata['paused_at']=stamp()
    state.phase='paused'
    store.put_task(state,state.revision,allow_resume=True)
    store.append_event(task_id,{'type':'task_paused','from_phase':state.metadata['paused_from_phase']})
    return state

@app.post('/api/tasks/{task_id}/resume')
async def resume(task_id:str,background_tasks:BackgroundTasks):
    state=get_task(task_id)
    if state.phase=='paused':
        previous=state.metadata.pop('paused_from_phase',state.phase)
        state.metadata.pop('paused_at',None)
        from .reviewers import ACTIVE_PHASES
        template_active={'queued','processing','template_parsing','template_local_ready','template_model_reviewing','template_review_failed','failed'}
        report_active={'queued','processing','analyzing','analysis_pending','failed'}
        if state.kind=='template' and previous in template_active:
            state.phase='queued';store.put_task(state,state.revision,allow_resume=True)
            background_tasks.add_task(run_template_graph,deps,task_id)
        elif state.kind=='report' and not state.fact_ref and previous in report_active:
            state.phase='queued';store.put_task(state,state.revision,allow_resume=True)
            background_tasks.add_task(run_report_graph,deps,task_id)
        elif state.kind=='report' and previous in ACTIVE_PHASES:
            state.phase=previous;store.put_task(state,state.revision,allow_resume=True)
            background_tasks.add_task(generate_draft,task_id,state.metadata.get('writing_review_run',{}).get('review_only',False))
        else:
            state.phase=previous;store.put_task(state,state.revision,allow_resume=True)
        store.append_event(task_id,{'type':'task_resumed','to_phase':state.phase})
        return state
    if state.kind=='template' and not state.metadata.get('confirmed_template_ref'):
        if state.phase not in ('template_review_failed','awaiting_template_confirmation','awaiting_review','failed'):
            raise HTTPException(409,'template_analysis_in_progress')
        state.phase='queued';store.put_task(state,state.revision)
        background_tasks.add_task(run_template_graph,deps,task_id)
        return state
    if state.kind=='report' and state.phase=='facts_frozen':return await preview_draft(task_id,background_tasks)
    if state.kind=='report' and state.result_refs.get('event_analysis') and state.phase=='awaiting_review':return state
    if state.kind=='report' and not state.fact_ref and state.phase in ('awaiting_review','failed','analysis_pending'):
        state.phase='queued';store.put_task(state,state.revision)
        background_tasks.add_task(run_report_graph,deps,task_id)
    return get_task(task_id)

class EventSettings(BaseModel):
    expected_revision:int
    threshold:float|None=Field(default=None,gt=0,le=1)
    groups:list[dict]|None=None
    merge_decisions:dict[str,str]=Field(default_factory=dict)
    themes:list[dict]|None=None
    briefs:dict[str,dict]=Field(default_factory=dict)
    draft_version:int|None=None

@app.post('/api/tasks/{task_id}/event-settings')
async def event_settings(task_id:str,req:EventSettings,background_tasks:BackgroundTasks):
    state=get_task(task_id)
    error,result=apply_event_settings(store,state,req)
    if error:raise HTTPException(*error)
    if result['run_graph']:background_tasks.add_task(run_report_graph,deps,task_id)
    return result['state']


class ReviewDraftRequest(BaseModel):
    expected_revision:int
    analysis_ref:str
    expected_version:int|None=None
    data:dict


@app.put('/api/tasks/{task_id}/review-draft')
def save_data_review_draft(task_id:str,req:ReviewDraftRequest):
    from .data_review import save_review_draft
    state=get_task(task_id)
    if state.revision!=req.expected_revision:raise HTTPException(409,'stale_decision')
    if state.result_refs.get('event_analysis')!=req.analysis_ref:raise HTTPException(409,'stale_review_draft')
    try:return save_review_draft(store,state,req.data,req.expected_version)
    except (ValueError,ConflictError) as exc:raise HTTPException(409,str(exc))

@app.get('/api/tasks/{task_id}/review-data')
def task_review_data(task_id:str):
    from .review_service import review_data
    get_task(task_id)
    return review_data(store,task_id)

@app.get('/api/tasks/{task_id}/draft-view')
def task_draft_view(task_id:str):
    from .review_service import draft_view
    get_task(task_id)
    try:return draft_view(store,task_id)
    except ValueError as exc:raise HTTPException(409,str(exc))

@app.get('/api/tasks/{task_id}/logs')
def task_logs(task_id:str):
    get_task(task_id)
    return JSONResponse(store.events(task_id),headers={'Content-Disposition':f'attachment; filename="task-{task_id}-logs.json"'})

@app.post('/api/tasks/{task_id}/cancel')
def cancel(task_id:str):
    state=get_task(task_id); state.cancel_requested=True; store.put_task(state,state.revision); return state

class Approval(BaseModel): draft_hash:str

class ChartUpdate(BaseModel):
    expected_hash:str
    styles:dict[str,str]=Field(default_factory=dict)

@app.post('/api/tasks/{task_id}/chart-settings')
async def update_chart_settings(task_id:str,req:ChartUpdate):
    from .chart_review import update_report_charts
    try:return await update_report_charts(store,task_id,req.expected_hash,req.styles)
    except (ValueError,KeyError) as exc:raise HTTPException(409,str(exc))

@app.get('/api/tasks/{task_id}/charts/{name}')
def current_chart(task_id:str,name:str):
    import base64
    state=get_task(task_id)
    if not state.draft_ref:raise HTTPException(404,'draft_missing')
    draft=store.get_artifact(state.draft_ref);ref=draft.get('chart_refs',{}).get(name)
    if not ref or ref not in draft.get('evidence_refs',[]):raise HTTPException(404,'chart_missing')
    chart=store.get_artifact(ref)
    if chart.get('fact_ref')!=state.fact_ref:raise HTTPException(409,'stale_chart_fact')
    return Response(base64.b64decode(chart['png_base64']),media_type='image/png')

class SlotValuePatch(BaseModel):
    values:dict[str,str|list[str]]
    expected_hash:str|None=None

class ReportParameters(BaseModel):
    expected_hash:str|None=None
    expected_revision:int|None=None
    issue_number:int|None=Field(default=None,ge=1)
    publication_date:str|None=None

@app.post('/api/tasks/{task_id}/report-parameters')
def set_report_parameters(task_id:str,req:ReportParameters):
    from .writing_review import edit_structured
    try:
        state=get_task(task_id)
        if req.expected_revision is not None and state.revision!=req.expected_revision:raise ValueError('stale_task_revision')
        parameters=req.model_dump(exclude={'expected_hash','expected_revision'},exclude_none=True)
        if state.draft_ref:return edit_structured(store,task_id,{},req.expected_hash,parameters)
        from .report_parameters import save_before_writing
        return save_before_writing(store,state,parameters,req.expected_revision)
    except (ValueError,KeyError) as exc:raise HTTPException(409,str(exc))

@app.post('/api/tasks/{task_id}/slot-values')
def fill_slot_values(task_id:str,req:SlotValuePatch):
    state=get_task(task_id)
    error,result=apply_slot_values(store,state,req)
    if error:raise HTTPException(*error)
    return result

class TemplateConfirm(BaseModel):
    expected_revision:int
    candidate_ref:str
    reason:str
    rules:dict|None=None
    resolutions:dict[str,str]=Field(default_factory=dict)


class TemplateExceptionCorrection(BaseModel):
    expected_revision:int
    input_ref:str
    candidate:dict
    reason:str


@app.get('/api/templates/{task_id}/exceptions')
def template_exceptions(task_id:str):
    from .template_exceptions import exception_view
    state=get_task(task_id)
    if state.kind!='template':raise HTTPException(422,'not_template_task')
    try:return exception_view(store,state)
    except ValueError as exc:raise HTTPException(409,str(exc))


@app.post('/api/templates/{task_id}/exceptions/{batch_id}/resolve')
async def resolve_template_exception(task_id:str,batch_id:str,req:TemplateExceptionCorrection,background_tasks:BackgroundTasks):
    from .template_exceptions import correct_batch
    state=get_task(task_id)
    if state.revision!=req.expected_revision:raise HTTPException(409,'stale_template_revision')
    if state.metadata.get('template_input_ref')!=req.input_ref:raise HTTPException(409,'stale_template_candidate')
    try:issues=correct_batch(store,state,batch_id,req.candidate,req.reason)
    except (ValueError,KeyError) as exc:raise HTTPException(409,str(exc))
    if issues:return JSONResponse({'detail':'template_correction_invalid','errors':issues},status_code=422)
    if state.phase=='queued':background_tasks.add_task(run_template_graph,deps,task_id)
    return {'revision':state.revision,'phase':state.phase,'remaining_batches':sum(b['status']=='human_required' for b in state.metadata['template_batches'].values())}

@app.get('/api/templates/{task_id}/definition')
def template_definition(task_id:str):
    state=get_task(task_id)
    ref=state.metadata.get('confirmed_template_ref') or state.metadata.get('structured_template_ref')
    if not ref: raise HTTPException(404,'structured_template_missing')
    from .structured_template import apply_top10_rule
    definition=store.get_artifact(ref)
    from .chart_spec import definitions
    definition['charts']=definitions(definition)
    if definition.get('status')=='candidate_requires_review':definition=apply_top10_rule(definition)
    questions=[dict(x,details=dict(x['details'])) for x in state.review_items if x['kind']=='template_business_question']
    if questions and state.metadata.get('template_input_ref'):
        packet=store.get_artifact(state.metadata['template_input_ref'])
        source_lookup={(d['id'],b['index']):b['text'] for d in packet['source_reports'] for b in d['blocks']}
        for question in questions:
            question['details']['sources']=[{**s,'text':source_lookup.get((s['report_id'],s['block']),'')} for s in question['details'].get('sources',[])]
    return {'revision':state.revision,'artifact_ref':ref,'definition':definition,
            'model_review_validated':bool(state.metadata.get('template_validation_ref')),
            'local_definition':store.get_artifact(state.metadata['local_template_ref']) if state.metadata.get('local_template_ref') else None,
            'questions':questions}

@app.get('/api/templates/{task_id}/sources')
def template_sources(task_id:str):
    from .ooxml import read_docx
    definition=template_definition(task_id)['definition']
    return [{'name':Path(source['path']).name,'blocks':read_docx(Path(source['path']))['blocks']} for source in definition['source_reports']]

@app.get('/api/templates/{task_id}/charts/{name}/source')
def template_chart_source(task_id:str,name:str,source_index:int=0):
    from .chart_spec import source_image
    try:
        definition=template_definition(task_id)['definition']
        if source_index<0:raise ValueError('invalid_source_index')
        data,mime=source_image(definition,name,source_index)
        return Response(data,media_type=mime)
    except (ValueError,KeyError,IndexError,StopIteration):raise HTTPException(404,'source_chart_unavailable')

class TemplateChartVersion(BaseModel):
    expected_revision:int
    styles:dict[str,str]

@app.post('/api/templates/{task_id}/chart-version')
def new_template_chart_version(task_id:str,req:TemplateChartVersion):
    from .chart_spec import with_styles
    state=get_task(task_id)
    if state.revision!=req.expected_revision:raise HTTPException(409,'stale_template_revision')
    ref=state.metadata.get('confirmed_template_ref')
    if state.kind!='template' or not ref:raise HTTPException(409,'confirmed_template_required')
    try:version=with_styles(store.get_artifact(ref),req.styles)
    except ValueError as exc:raise HTTPException(422,str(exc))
    version.update(parent_ref=ref,version=int(version.get('version',1))+1,human_reason='人工调整图表样式；沿用已确认的正文与统计口径')
    new_ref=store.put_artifact(task_id,'template_version',version)
    state.metadata['confirmed_template_ref']=new_ref;store.put_task(state,state.revision)
    store.append_event(task_id,{'type':'human_template_chart_version','parent_ref':ref,'template_ref':new_ref,'styles':req.styles})
    return {'template_ref':new_ref,'revision':state.revision}

class TemplateDefinitionPatch(BaseModel):
    expected_revision:int
    fields:dict[str,dict]=Field(default_factory=dict)
    rules:dict|None=None
    chart_styles:dict[str,str]|None=None

@app.put('/api/templates/{task_id}/definition')
def revise_template_definition(task_id:str,req:TemplateDefinitionPatch):
    state=get_task(task_id)
    error,_=apply_definition_patch(store,state,req)
    if error: raise HTTPException(*error)
    return template_definition(task_id)

@app.post('/api/templates/{task_id}/confirm')
def confirm_template(task_id:str,req:TemplateConfirm):
    state=get_task(task_id)
    error,result=confirm_candidate(store,state,req)
    if error: raise HTTPException(*error)
    return result

@app.post('/api/tasks/{task_id}/approve')
def approve(task_id:str,req:Approval):
    state=get_task(task_id)
    from .reviewers import ACTIVE_PHASES
    if state.phase in ACTIVE_PHASES:raise HTTPException(409,'writing_in_progress')
    if not state.fact_ref:raise HTTPException(409,'data_review_required')
    if not state.draft_ref: raise HTTPException(409,'draft_missing')
    if state.metadata.get('preview_only'): raise HTTPException(409,'preview_cannot_be_approved')
    draft=store.get_artifact(state.draft_ref)
    if state.template_ref=='anshun-monthly-colored':
        from .slot_writer import WRITER_SLOT_IDS
        unfilled=[s for s in sorted(WRITER_SLOT_IDS) if not (draft.get('slot_values',{}).get(s) or {}).get('value')]
        if unfilled: raise HTTPException(409,'writer_slots_unfilled:'+','.join(unfilled))
    if req.draft_hash!=draft['content_hash']: raise HTTPException(409,'stale_draft')
    problems=validate_draft(DraftVersion.model_validate(draft),store.get_artifact(draft['fact_ref']))
    if any(x.severity=='blocking' for x in problems): raise HTTPException(409,'draft_validation_failed')
    if any(x['blocking'] and x['status']!='resolved' for x in state.review_items): raise HTTPException(409,'unresolved_blockers')
    if draft.get('structured_template_ref'):
        try:export_docx(draft,store.get_artifact(state.fact_ref),None,'final',[],local_store=store)
        except (ValueError,KeyError) as exc:raise HTTPException(409,'report_incomplete:'+str(exc))
    from .reviewers import review_ready
    if not review_ready(state,draft['content_hash']):raise HTTPException(409,'writing_review_required')
    state.metadata['approval_hash']=req.draft_hash; state.phase='approved'; store.put_task(state,state.revision)
    store.append_event(task_id,{'type':'final_approval','draft_hash':req.draft_hash})
    return state

class ExportRequest(BaseModel): mode:str='draft'
@app.post('/api/tasks/{task_id}/exports')
def export(task_id:str,req:ExportRequest):
    state=get_task(task_id)
    if not state.fact_ref:raise HTTPException(409,'data_review_required')
    if req.mode not in ('draft','final'): raise HTTPException(422,'invalid_mode')
    if not state.draft_ref: raise HTTPException(409,'draft_missing')
    draft=store.get_artifact(state.draft_ref)
    if req.mode=='final' and state.metadata.get('approval_hash')!=draft['content_hash']: raise HTTPException(409,'current_approval_required')
    issues=[x for x in state.review_items if x['status']!='resolved']
    data=export_docx(draft,store.get_artifact(draft['fact_ref']),None,req.mode,issues,local_store=store)
    ref=store.put_artifact(task_id,'export_meta',{'mode':req.mode,'fact_ref':draft['fact_ref'],'draft_hash':draft['content_hash'],'sha256':hashlib.sha256(data).hexdigest()})
    path=DATA/'artifacts'/f'{ref}.docx'; path.write_bytes(data)
    return {'artifact_id':ref,'download_url':f'/api/artifacts/{ref}/download','sha256':hashlib.sha256(data).hexdigest()}

@app.get('/api/artifacts/{artifact_id}')
def artifact(artifact_id:str):
    try: return store.get_artifact(artifact_id)
    except KeyError: raise HTTPException(404,'artifact_not_found')
@app.get('/api/artifacts/{artifact_id}/chart')
def chart_image(artifact_id:str):
    import base64
    try: data=store.get_artifact(artifact_id)
    except KeyError: raise HTTPException(404,'artifact_not_found')
    if 'png_base64' not in data: raise HTTPException(422,'not_chart')
    return Response(base64.b64decode(data['png_base64']),media_type='image/png')
@app.get('/api/artifacts/{artifact_id}/download')
def download(artifact_id:str):
    store.get_artifact(artifact_id)
    path=DATA/'artifacts'/f'{artifact_id}.docx'
    if not path.exists(): raise HTTPException(404,'download_not_found')
    return FileResponse(path,media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',filename='安顺月报结构演示稿.docx')
