"""Model-facing integer citations; canonical IDs are bound only by program code."""
from typing import Any,Annotated
from pydantic import BaseModel,ConfigDict,Field,RootModel,ValidationError
import copy
from .section_two import RiskChain,AnalysisPlan,OutlookItem
from .state import WritingPatch

SourceNumber=Annotated[int,Field(strict=True,ge=1)]

class NumberedValue(BaseModel):
    model_config=ConfigDict(extra='forbid')
    value:Any
    source_refs:list[SourceNumber]=Field(min_length=1)

class NumberedChain(RiskChain):
    source_refs:list[SourceNumber]=Field(min_length=1)

class NumberedAnalysis(AnalysisPlan):
    chains:list[NumberedChain]=Field(min_length=2,max_length=2)

class NumberedOutlook(OutlookItem):
    history_refs:list[SourceNumber]=Field(min_length=1)

class NumberedAnswers(BaseModel):
    model_config=ConfigDict(extra='forbid')
    values:dict[str,NumberedValue]=Field(default_factory=dict)
    analysis_plan:NumberedAnalysis|None=None
    outlook_items:list[NumberedOutlook]|None=Field(default=None,min_length=4,max_length=5)

class NumberedOutlookRepairAnswers(NumberedAnswers):
    outlook_items:list[NumberedOutlook]|None=Field(default=None,min_length=1,max_length=5)

class NumberedPatch(WritingPatch):
    source_refs:list[SourceNumber]=Field(default_factory=list)

class NumberedRevision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    patches:list[NumberedPatch]=Field(default_factory=list,max_length=12)

class NumberedSlot(BaseModel):
    model_config=ConfigDict(extra='forbid')
    slot_id:str
    value:str
    source_refs:list[SourceNumber]=Field(default_factory=list)

class RawWriterReply(RootModel[dict]):pass

class ReferenceSelection(BaseModel):
    model_config=ConfigDict(extra='forbid')
    path:str
    source_refs:list[SourceNumber]=Field(min_length=1)

class ReferenceRepair(BaseModel):
    model_config=ConfigDict(extra='forbid')
    selections:list[ReferenceSelection]=Field(default_factory=list)

class SourceBindingError(ValueError):
    def __init__(self,raw,requests):
        self.raw=raw;self.requests=requests
        super().__init__('引用尚未绑定；请只补选已登记资料编号，保留已生成正文。位置：'+','.join(r['path'] for r in requests))


class SourceCatalog:
    """Numbers are scoped to one writer run and never reassigned mid-call."""
    def __init__(self,allowed):
        self.allowed=allowed  # The caller may add trusted tool results in-place.
        self.mapping={}
        self.reverse={}

    def register(self,ref):
        if ref not in self.allowed:raise ValueError('source_not_registered_by_program')
        if ref not in self.reverse:
            number=len(self.mapping)+1;self.mapping[number]=ref;self.reverse[ref]=number
        return self.reverse[ref]

    def project(self,value,key=None):
        """Replace exact trusted ref values, never rewrite prose or facts."""
        if isinstance(value,dict):return {name:self.project(item,name) for name,item in value.items()}
        if isinstance(value,list):return [self.project(item,key) for item in value]
        prose={'value','paragraph','text','summary','title','description','instruction','reason','rule','knowledge_basis','historical_basis','before','after'}
        if isinstance(value,str) and key not in prose and value in self.allowed:return self.register(value)
        return value

    def bind(self,value):
        if isinstance(value,list):return [self.bind(item) for item in value]
        if not isinstance(value,dict):return value
        result={}
        for key,item in value.items():
            if key in ('source_refs','history_refs'):
                unknown=[n for n in item if type(n) is not int or n not in self.mapping]
                if unknown:raise ValueError('未知资料编号：'+str(unknown)+'；只能选择当前目录编号：'+str(list(self.mapping)))
                result[key]=[self.mapping[n] for n in item]
            else:result[key]=self.bind(item)
        return result

    def normalize(self,value):
        if isinstance(value,list):return [self.normalize(item) for item in value]
        if not isinstance(value,dict):return value
        result={}
        for key,item in value.items():
            if key in ('source_refs','history_refs') and isinstance(item,list):
                result[key]=[self.reverse[n] if isinstance(n,str) and n in self.reverse else int(n) if isinstance(n,str) and n.isdecimal() and int(n) in self.mapping else n for n in item]
            else:result[key]=self.normalize(item)
        return result

    def decode(self,raw,model):
        normalized=self.normalize(raw);requests=[]
        def visit(value,path=()):
            if isinstance(value,list):
                for index,item in enumerate(value):visit(item,(*path,str(index)))
            elif isinstance(value,dict):
                for key,item in value.items():
                    if key in ('source_refs','history_refs') and (not isinstance(item,list) or not item or any(type(n) is not int or n not in self.mapping for n in item)):
                        # Empty revision citations and the legacy insufficient-
                        # evidence answer are valid; no canonical ID is guessed.
                        if not item and ('patches' in path or 'slot_id' in value):continue
                        requests.append({'path':'.'.join((*path,key)),'context':{k:v for k,v in value.items() if k not in ('source_refs','history_refs')}})
                    else:visit(item,(*path,key))
                required='history_refs' if path and path[0]=='outlook_items' else 'source_refs' if 'chains' in path or path and path[0]=='values' and 'value' in value else None
                if required and required not in value:requests.append({'path':'.'.join((*path,required)),'context':value})
        visit(normalized)
        try:wire=model.model_validate(normalized)
        except ValidationError as exc:
            if requests and all(any(part in ('source_refs','history_refs') for part in e['loc']) for e in exc.errors()):raise SourceBindingError(normalized,requests) from exc
            raise
        if requests:raise SourceBindingError(normalized,requests)
        return self.bind(wire.model_dump())

    def schema(self,schema):
        """Keep confirmed value rules while making citation lists integer-only."""
        if isinstance(schema,list):return [self.schema(item) for item in schema]
        if not isinstance(schema,dict):return schema
        result={key:self.schema(item) for key,item in schema.items()}
        for key in ('source_refs','history_refs'):
            if key in result.get('properties',{}):
                result['properties'][key]['items']={'type':'integer','minimum':1}
        return result

    def audit(self,store,task_id,stage,targets):
        ref=store.put_artifact(task_id,'writer_source_catalog',{'protocol':'numbered-v1','stage':stage,'targets':targets,
            'sources':[{'number':n,'ref':ref} for n,ref in self.mapping.items()]})
        store.append_event(task_id,{'type':'writer_source_catalog','ref':ref,'stage':stage,'targets':targets,'count':len(self.mapping)})
        return ref


async def invoke_numbered_writer(catalog,payload,model,context,response_schema=None,tools=None,tool_executor=None,repair=None):
    from .model_client import invoke_agent
    from .agent import get_prompt
    projected=catalog.project(payload)
    if repair:
        request={'instruction':get_prompt('writer.reference_repair',payload.get('prompt_profile','anshun_monthly')),
                 'reference_requests':repair.requests,'allowed_numbers':list(catalog.mapping),
                 'evidence':projected.get('evidence',[]),'report_context':projected.get('report_context',projected.get('frozen_context')),
                 'historical_research':projected.get('historical_research')}
        reply=await invoke_agent('writer',request,RawWriterReply,context,response_schema=ReferenceRepair.model_json_schema())
        selections=ReferenceRepair.model_validate(catalog.normalize(reply.root)).selections
        if {s.path for s in selections}!={r['path'] for r in repair.requests} or len(selections)!=len(repair.requests):raise SourceBindingError(repair.raw,repair.requests)
        updated=copy.deepcopy(repair.raw)
        for selection in selections:
            node=updated;parts=selection.path.split('.')
            for part in parts[:-1]:node=node[int(part)] if isinstance(node,list) else node[part]
            node[parts[-1]]=selection.source_refs
        context.store.append_event(context.task_id,{'type':'writer_reference_repair','paths':[s.path for s in selections],'body_preserved':True})
        return catalog.decode(updated,model)
    reply=await invoke_agent('writer',projected,RawWriterReply,context,response_schema=response_schema or model.model_json_schema(),tools=tools,tool_executor=tool_executor)
    if catalog.normalize(reply.root)!=reply.root:context.store.append_event(context.task_id,{'type':'writer_source_normalized','method':'exact_registered_ref_or_integer_string','body_preserved':True})
    return catalog.decode(reply.root,model)
