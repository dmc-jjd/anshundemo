"""Knowledge-led candidate comparison with optional source verification."""
from .agent import get_prompt,DEFAULT_PROMPT_PROFILE,prompt_fingerprint
import uuid
from .section_two import HistoricalResearch,HistoryTopic,CandidateComparison,forecast_window,validate_history,POLICY_VERSION,source_excerpts,seasonal_knowledge_usable
from .model_client import invoke_agent
from .tool_executor import execute_tool
from .schemas import ToolCall
from .historical_web import HANDLERS,native_tools,page_read_error

async def prepare_history(report,context,profile=DEFAULT_PROMPT_PROFILE):
    store=context.store;task_id=context.task_id;window=forecast_window(report)
    fingerprint=prompt_fingerprint(profile,('historical_researcher.',))
    state=store.get_task(task_id);prior=state.metadata.get('historical_research_ref')
    refs=set();errors=[];topics=[];comparison=None;comparison_ref=None
    if prior:
        data=store.get_artifact(prior)
        same_prompt=data.get('prompt_fingerprint')==fingerprint if data.get('prompt_fingerprint') else profile==DEFAULT_PROMPT_PROFILE
        readable=all(not page_read_error(store.get_artifact(ref).get('content','')) for ref in data.get('source_refs',[]) if ref.startswith('historical_page-'))
        if same_prompt and readable and data.get('policy_version')==POLICY_VERSION and data.get('window')==window and data.get('status')=='ready':return prior,data
        if data.get('window',{}).get('report_month')==window['report_month']:
            refs.update(data.get('source_refs',[]))
            if same_prompt and data.get('policy_version')==POLICY_VERSION:
                topics=data.get('topics',[]);comparison=data.get('candidate_comparison');comparison_ref=data.get('comparison_ref')
    from .historical_reader import HistoricalReader
    reader=HistoricalReader(context,refs)
    async def run_tool(name,args):
        if name not in HANDLERS:return {'error':'historical_tool_not_allowed'}
        packet=await (reader.fetch(args) if name=='fetch_historical_page' else reader.search(args))
        if name=='fetch_historical_page' and 'data' in packet:packet['data']['note']=get_prompt('historical_researcher.page_note',profile)
        return packet
    for attempt in range(3):
        store.append_event(task_id,{'type':'historical_research_started','round':attempt+1,'window':window})
        try:
            pages=[];results=[];unreadable=[]
            for ref in sorted(refs):
                item=store.get_artifact(ref)
                if 'content' in item:
                    error=page_read_error(item['content'])
                    if error:unreadable.append({'ref':ref,'url':item.get('url'),'reason':error})
                    else:pages.append({'ref':ref,**{k:item.get(k) for k in ('url','title','published_at')},'excerpts':source_excerpts(item['content'])})
                elif 'results' in item:
                    from .historical_reader import url_key
                    results.extend({'search_ref':ref,**r} for r in item['results'] if url_key(r['url']) not in reader.state['failed_urls'])
            pages.sort(key=lambda p:(bool(p.get('published_at') and p['published_at'][:10]<=window['as_of']),p.get('published_at') or ''),reverse=True)
            if comparison is None:
                planned=await invoke_agent('historical_researcher',{'instruction':get_prompt('historical_researcher.plan',profile),
                    'prompt_profile':profile,'forecast':window,'current_category_counts':report.categories_for(),
                    'existing_source_summaries':[{k:p.get(k) for k in ('ref','url','title','published_at')} for p in pages[:16]],
                    'correction_errors':errors},CandidateComparison,context)
                comparison=planned.model_dump()
                if len({c['id'] for c in comparison['candidates']})!=len(comparison['candidates']) or len({c['category'] for c in comparison['candidates']})!=len(comparison['candidates']):
                    comparison=None;raise ValueError('风险候选ID和类别必须各自唯一，候选比较须为5—8类')
                comparison_ref=store.put_artifact(task_id,'risk_comparison',{'window':window,'comparison':comparison,'source_type':'model_knowledge_candidates'})
                store.append_event(task_id,{'type':'risk_candidate_comparison','ref':comparison_ref,'candidate_count':len(comparison['candidates']),'network_tools_allowed':False})
            answer=await invoke_agent('historical_researcher',{'instruction':get_prompt('historical_researcher.research',profile),'prompt_profile':profile,'forecast':window,
                'current_context':{'category_counts':report.categories_for(),'note':get_prompt('historical_researcher.current_note',profile)},
                'candidate_comparison':comparison,'correction_errors':errors,'previous_topics':topics,'already_read_pages':pages[:16],'unreadable_pages':unreadable,
                'available_search_results':results[:24]},HistoricalResearch,context,tools=native_tools(),tool_executor=run_tool)
            ids={c['id'] for c in comparison['candidates']}
            if any(t.candidate_id not in ids for t in answer.topics):raise ValueError('选题必须引用已经比较的candidate_id')
            if len({t.candidate_id for t in answer.topics})!=len(answer.topics):raise ValueError('不能把同一候选重复选为多类风险')
            topics,errors=validate_history(answer,store,task_id,window,refs)
            store.append_event(task_id,{'type':'historical_validation','round':attempt+1,'topic_count':len(topics),'errors':errors})
            if len({t['category'] for t in topics})>=4:break
        except Exception as exc:errors=[type(exc).__name__+':'+str(exc)[:1200]]
    fallback_categories=[]
    if comparison and len({t['category'] for t in topics})<4:
        # Reuse the model's own compared seasonal candidates. No new facts,
        # network requests, model calls or invented historical citations.
        selected_ids={t['candidate_id'] for t in topics};selected_categories={t['category'] for t in topics}
        for candidate in comparison['candidates']:
            if candidate['id'] in selected_ids or candidate['category'] in selected_categories or candidate['basis_type']!='seasonal' or not seasonal_knowledge_usable(candidate['knowledge_basis']):continue
            fallback=HistoryTopic(candidate_id=candidate['id'],category=candidate['category'],basis_type='seasonal',
                knowledge_basis=candidate['knowledge_basis'],applies_to_months=[int(p[5:]) for p in window['periods']],rationale=candidate['comparison_reason'])
            qualified,_=validate_history(HistoricalResearch(topics=[fallback]),store,task_id,window,refs)
            if qualified:
                topics.extend(qualified);fallback_categories.append(candidate['category']);selected_ids.add(candidate['id']);selected_categories.add(candidate['category'])
            if len({t['category'] for t in topics})>=5:break
        if fallback_categories:store.append_event(task_id,{'type':'historical_seasonal_fallback','categories':fallback_categories,'new_model_calls':0,'verified_local_history':False})
    data={'policy_version':POLICY_VERSION,'prompt_profile':profile,'prompt_fingerprint':fingerprint,'window':window,'seasonal_fallback_categories':fallback_categories,
          'candidate_comparison':comparison,'comparison_ref':comparison_ref,'topics':topics,'status':'ready' if comparison and len({t['category'] for t in topics})>=4 else 'insufficient',
          'errors':errors,'source_refs':sorted(refs)}
    ref=store.put_artifact(task_id,'historical_research',data)
    state=store.get_task(task_id);state.metadata['historical_research_ref']=ref;store.put_task(state,state.revision)
    store.append_event(task_id,{'type':'historical_research_result','ref':ref,'status':data['status'],'topic_count':len(topics),'errors':errors})
    return ref,data
