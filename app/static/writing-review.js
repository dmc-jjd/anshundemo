// Model reviews end before final human edits. All saves below are local operations.
Object.assign(phases,{style_detection:'正在检测第二部分表达',format_review:'格式审核员正在审查',content_review:'内容审核员正在审查',final_format_review:'最终格式校验中',revising:'Writer正在按审核意见修改'});
Object.assign(errors,{writing_review_required:'当前稿尚未完成双审核，请查看“双审核与人工终审”。',use_writing_review_editor:'请在双审核页面查看原句并处理。',writing_review_reason_required:'请填写人工核查说明。',review_excerpt_not_found:'这处原句已被之前的修改更新，请对照当前整段内容核查。',review_excerpt_location_required:'原句出现多次，请选择需要替换的位置。',review_excerpt_location_changed:'原句位置已变化，请重新打开审核页。',review_excerpt_empty:'修改后的文字不能为空。',review_excerpt_unchanged_use_retain:'文字没有修改，请点击保留当前内容。',stale_draft_hash:'稿件已更新，请重新打开审核页；未提交的逐条编辑会保留。',writing_review_not_at_human_stage:'自动审核尚未结束，请完成后再作人工终审。'});
const writingExcerptDrafts=new Map();
const writingBusy=p=>['writing','style_detection','format_review','content_review','final_format_review','revising'].includes(p);
const writingRole={format_reviewer:'格式审核员',content_reviewer:'内容审核员'};
const graphNames={validate_input:'核对输入',data_processing:'处理数据',event_analysis:'研判事件',await_data_review:'等待数据审核',write_draft:'Writer写作',local_validation:'本地校验',style_detection:'表达检测',format_review:'格式审核',content_review:'内容审核',revise_draft:'Writer退修',final_format_review:'最终格式校验',await_final_review:'等待人工终审'};
const reviewState={passed:'未发现待修改问题',issues:'已给出审查意见',error:'审查未完成',human_confirmed:'人工已最终核查'};
function reviewSummaryItems(summary){
 const items=[],stack=[],pairs={'“':'”','「':'」','『':'』','（':'）','(':')'};let part='';
 for(const char of summary||''){
  part+=char;
  if(pairs[char])stack.push(pairs[char]);else if(stack.at(-1)===char)stack.pop();
  if(!stack.length&&/[。；;\n]/.test(char)){if(part.trim())items.push(part.trim());part=''}
 }
 if(part.trim())items.push(part.trim());return items;
}
const detailBeforeWritingReview=detail;
detail=async function(id,force=false){
 await detailBeforeWritingReview(id,force);const state=await api(`/api/tasks/${id}`);
 if(state.kind!=='report'||!state.draft_ref)return;
 const actions=$('#taskActions');if(!$('#writingReviewAction')){const b=button('双审核与人工终审',()=>openWritingReview(id));b.id='writingReviewAction';actions.append(b)}
 if(writingBusy(state.phase))for(const b of actions.querySelectorAll('button'))if(/重新生成|开始按模板|下载当前/.test(b.textContent))b.disabled=true;
 let hint=$('#writingReviewHint');if(!hint){hint=node('p',null,{id:'writingReviewHint',class:'help'});$('#taskDetail').append(hint)}
 hint.textContent=writingBusy(state.phase)?phases[state.phase]+'。自动阶段结束后再作人工终审。':state.metadata.review_report?'格式、内容审核结果及退修记录可在“双审核与人工终审”查看。':'当前历史稿尚未经过双审核，可打开“双审核与人工终审”审核当前稿。';
};

async function openWritingReview(id){
 openDialog('双审核与人工终审');const body=$('#dialogBody');body.textContent='正在读取当前稿的审核结果…';
 const [x,view,state]=await Promise.all([api(`/api/tasks/${id}/writing-review`),api(`/api/tasks/${id}/draft-view`),api(`/api/tasks/${id}`)]);
 const current=x.report?.draft_hash===x.draft_hash,editable=state.phase==='awaiting_final_review',active=writingBusy(state.phase);
 const contentRound=x.run?.stage_rounds?.content_reviewer,formatRepairs=x.run?.stage_repair_attempts?.format_reviewer||0;
 body.replaceChildren(node('p',`${contentRound?'内容审核第 '+contentRound+' / 5 轮':'格式审核'}；格式已退修 ${formatRepairs} / 5 次 → Writer按意见退修 → 人工最终核查。两阶段分别限次；人工保存后直接进入终审，不再回到模型。`,{class:'help'}));
 const summary=node('section',null,{class:'review-summary'});
 for(const role of Object.keys(writingRole)){const r=current?x.report.reviewers?.[role]:null,card=node('div',null,{class:'member-card'});card.dataset.reviewer=role;card.append(node('h3',writingRole[role]),node('strong',r?reviewState[r.status]||r.status:active?'等待本轮结果':'当前稿尚未审核'));if(r?.summary){const points=node('ol',null,{class:'review-summary-list','aria-label':writingRole[role]+'意见概述'});reviewSummaryItems(r.summary).forEach(text=>points.append(node('li',text)));card.append(points)}summary.append(card)}body.append(summary);
 body.append(node('p',x.ready?'双审核及待办已处理。报告字段与图表完整后，可确认终审。':active?'自动写作与审核正在执行，下面仅展示当前进展。':!current?'需要先完成当前稿的格式、内容审核。':`当前还有 ${x.issues.filter(i=>i.blocking).length} 项阻断意见，请查看原句并最终处理。`,{class:x.ready?'help':'notice'}));
 if(x.run?.format_limit_reached)body.append(node('p','格式审核已到重试上限，已保留格式意见并继续内容审核。遗留格式问题与内容意见在此统一作最终人工核查。',{class:'notice'}));
 if(view.missing?.length)body.append(node('p',`另外还有 ${view.missing.length} 个字段未完成；在“查看报告与缺失项”补全。`,{class:'notice'}));
 if(x.run?.repair_error){body.append(node('p',active?'退修未通过校验，已保留有效正文，正在反馈错误并继续审核。':'自动退修已达本阶段上限，已保留上一版有效正文。请按下方原句完成最终人工核查。',{class:'notice'}));const technical=node('details');technical.append(node('summary','查看退修校验原因'),node('pre',x.run.repair_error));body.append(technical)}
 const reason=node('textarea',null,{rows:'2','aria-label':'补充核查说明（选填）',placeholder:'例如：已对照来源核查，该表述符合本期报告口径，保留当前内容。'});
 if(x.issues.length&&editable)body.append(node('label','补充核查说明（选填，直接点击保留也可完成核查）'),reason);
 pendingSourceEditors(id,view,body);
 const definitions=Object.fromEntries((view.definition?.fields||[]).map(f=>[f.id,f]));
 for(const issue of x.issues){
  const d=issue.details,number=issue.number,card=node('section',null,{class:'member-card writing-finding'});card.dataset.issueId=issue.id;card.dataset.reviewNumber=number;
  const heading=node('h3');heading.append(node('span',number+'. ',{class:'review-number'}),document.createTextNode((writingRole[issue.reviewer]||'审查')+' · '+(definitions[d.field_id]?.display_name||(d.field_id==='__review__'?'审查未完成':d.field_id))));
  card.append(heading,node('p',issue.blocking?'需处理后终审':'建议核查',{class:'help'}));
  const canEdit=editable&&definitions[d.field_id]?.owner==='writer'&&d.quote,locations=issue.locations||[],draftKey=id+':'+issue.id;
  let input=null,locationSelect=null;
  if(d.quote){
   if(canEdit){
    const label=node('label','引用原文（可直接编辑）');input=node('textarea',null,{rows:'3',class:'review-quote','aria-label':'第'+number+'条原文'});
    const cached=writingExcerptDrafts.get(draftKey);input.value=cached?.quote===d.quote?cached.value:d.quote;
    input.oninput=()=>{if(input.value===d.quote)writingExcerptDrafts.delete(draftKey);else writingExcerptDrafts.set(draftKey,{quote:d.quote,value:input.value})};
    if(!locations.length)input.readOnly=true;label.append(input);card.append(label);
   }else card.append(node('blockquote',d.quote));
  }
  if(d.field_id==='__review__'){card.append(node('p','该审核员未取得有效审查结果。可重试，或由人工最终核查全文。'));const technical=node('details');technical.append(node('summary','查看调用或校验原因'),node('pre',d.description||''));card.append(technical)}else card.append(node('p',d.description||issue.question));
  if(d.suggestion)card.append(node('p','修改建议：'+d.suggestion,{class:'review-suggestion'}));
  if(canEdit){
   if(locations.length>1){const label=node('label','原句出现多次，请选择覆盖位置');locationSelect=node('select',null,{'aria-label':'第'+number+'条覆盖位置'});locationSelect.append(node('option','请选择需要替换的位置',{value:''}));locations.forEach((loc,index)=>locationSelect.append(node('option',(loc.paragraph_index==null?'正文':'第'+(loc.paragraph_index+1)+'条')+' · 第'+(index+1)+'处',{value:String(index)})));label.append(locationSelect);card.append(label)}
   const context=node('details');context.append(node('summary','对照当前完整内容'));const value=view.draft.slot_values[d.field_id].value;(Array.isArray(value)?value:[value]).forEach((text,index)=>context.append(node('p',(Array.isArray(value)?(index+1)+'. ':'')+text)));card.append(context);
   if(!locations.length)card.append(node('p','这处引用已随之前的修订变化。请展开当前完整内容核查，或使用下方的整段修订。',{class:'help'}));
  }
  if(editable){
   const actions=node('div',null,{class:'review-item-actions'});
   actions.append(button('已核对，保留当前内容',async()=>{await post(`/api/tasks/${id}/writing-review/resolve`,{expected_hash:x.draft_hash,issue_ids:[issue.id],reason:reason.value.trim()});writingExcerptDrafts.delete(draftKey);await openWritingReview(id);shownRevision=null;await refresh(true)}));
   if(canEdit&&locations.length)actions.append(button('保存本处修改并覆盖终稿',async()=>{
    if(!input.value.trim())throw Error('修改后的文字不能为空。');if(input.value===d.quote)throw Error('文字没有修改，请点击保留当前内容。');
    if(locationSelect&&locationSelect.value==='')throw Error('原句出现多次，请选择需要替换的位置。');
    const location=locations[locationSelect?Number(locationSelect.value):0];
    await post(`/api/tasks/${id}/writing-review/${issue.id}/edit`,{expected_hash:x.draft_hash,replacement:input.value,location});writingExcerptDrafts.delete(draftKey);
    toast('已覆盖终稿对应原句，其他文字保持；本条意见已处理，未调用模型。');await openWritingReview(id);shownRevision=null;await refresh(true);
   },true));card.append(actions);
  }
  body.append(card);
 }
 if(x.resolved_issues?.length){
  body.append(node('h3','多轮退修后仍未自动解决的问题'));
  for(const issue of x.resolved_issues){
   const d=issue.details,card=node('section',null,{class:'member-card writing-finding'});
   card.append(node('h3',(writingRole[issue.reviewer]||'审查')+' · '+(definitions[d.field_id]?.display_name||d.field_id)));
   card.append(node('p','已人工处理；以下保留审核时原文与修改意见。',{class:'help'}));
   if(d.quote)card.append(node('blockquote',d.quote));
   card.append(node('p',d.description||issue.question));
   if(d.suggestion)card.append(node('p','修改建议：'+d.suggestion,{class:'review-suggestion'}));
   if(issue.decision?.reason)card.append(node('p','人工处理：'+issue.decision.reason,{class:'help'}));
   body.append(card);
  }
 }

 const fields=[...new Set(x.issues.map(i=>i.details.field_id))].filter(key=>definitions[key]?.owner==='writer'&&view.draft.slot_values[key]);
 if(fields.length&&editable){body.append(node('h3','整段修订（需要通篇调整时使用）'));for(const key of fields){const answer=view.draft.slot_values[key],card=node('details');card.dataset.fieldId=key;card.append(node('summary',definitions[key].display_name||key));const list=Array.isArray(answer.value),values=list?answer.value:[answer.value],inputs=values.map((v,i)=>{const label=node('label',list?'第 '+(i+1)+' 条':'正文'),input=node('textarea',null,{rows:'6','aria-label':(definitions[key].display_name||key)+(list?' 第'+(i+1)+'条':'')});input.value=v;label.append(input);card.append(label);return input});
   card.append(button('保存人工终稿（不调用模型）',async()=>{const texts=inputs.map(input=>input.value.trim());if(texts.some(v=>!v))throw Error('正文不可为空。');await post(`/api/tasks/${id}/slot-values`,{expected_hash:x.draft_hash,values:{[key]:list?texts:texts[0]}});toast('人工终稿已保存，该字段审查意见已处理，未调用模型。');await openWritingReview(id);shownRevision=null;await refresh(true)},true));body.append(card)
  }}
 const history=node('details');history.append(node('summary','表达检测与退修记录（不是AI生成概率）'));
 for(const [index,item] of (x.style_history||[]).entries()){const d=node('details');d.append(node('summary',`第 ${index+1} 次检测：${item.semantic_candidates.length} 个待语义核对片段，${item.project_findings.length} 处方法说明`));const metrics=node('pre',JSON.stringify(item.metrics,null,2));d.append(node('p','同一 skill 规则在修改前后分别运行，语义候选不等于写作错误。',{class:'help'}),metrics);history.append(d)}
 for(const [index,repair] of (x.repairs||[]).entries()){const d=node('details');d.append(node('summary',`第 ${index+1} 次自动退修`));for(const patch of repair.patches){d.append(node('h4',definitions[patch.field_id]?.display_name||patch.field_id),node('p','修改前'),node('blockquote',Array.isArray(patch.before)?patch.before.join('\n\n'):patch.before),node('p','修改后'),node('blockquote',Array.isArray(patch.after)?patch.after.join('\n\n'):patch.after))}history.append(d)}
 if(!(x.style_history||[]).length)history.append(node('p','当前稿尚无检测记录。'));body.append(history);
 const trace=node('details');trace.append(node('summary','查看实际图节点执行记录'));const table=node('table');for(const e of x.graph_nodes){const row=node('tr');row.append(node('td',graphNames[e.node]||e.node),node('td',({started:'开始',finished:'完成',error:'未完成'})[e.status]||e.status),node('td',new Date(e.at).toLocaleTimeString('zh-CN')));table.append(row)}trace.append(table,node('a','查看编译图结构',{href:'/api/workflow-graphs',target:'_blank'}));body.append(trace);
 if(!active&&state.phase!=='approved')$('#dialogActions').append(button(current?'重试未完成审核':'审核当前稿',async()=>{await post(`/api/tasks/${id}/review-draft`,{expected_hash:x.draft_hash});$('#reviewDialog').close();toast('已启动当前稿双审核，保留已完成人工文字。');shownRevision=null;await refresh(true)}));
 if(view.can_approve&&state.phase!=='approved')$('#dialogActions').append(button('确认报告并终审',async()=>{await post(`/api/tasks/${id}/approve`,{draft_hash:x.draft_hash});$('#reviewDialog').close();toast('报告已通过终审。');shownRevision=null;await refresh(true)},true));
}

const openDraftBeforeWritingReview=openDraft;
openDraft=async function(id){await openDraftBeforeWritingReview(id);const view=await api(`/api/tasks/${id}/draft-view`);$('#dialogActions').prepend(button('查看双审核意见',()=>openWritingReview(id)));if(!view.can_approve&&!view.review_ready){const hint=$('#dialogActions').querySelector('p');if(hint)hint.textContent='当前稿需完成双审核并处理待办；详见“查看双审核意见”。'}};
