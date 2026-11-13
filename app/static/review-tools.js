let flowClock=null;
function durationText(ms){if(ms>0&&ms<1000)return Math.round(ms)+'毫秒';const sec=Math.max(0,Math.floor(ms/1000)),h=Math.floor(sec/3600),m=Math.floor(sec%3600/60),s=sec%60;return (h?h+'小时 ':'')+(m||h?m+'分 ':'')+s+'秒'}
function tickFlowClock(){if(!flowClock)return;const x=flowClock.value,frozen=!!x.ended_at||x.current_phase==='paused',delta=frozen?0:Math.max(0,Date.now()-flowClock.received);for(const key of ['total_ms','processing_ms','human_wait_ms','recovery_wait_ms']){const n=document.querySelector(`[data-flow-clock="${key}"]`);if(n)n.textContent=durationText(x[key]+((key==='total_ms'||key===x.current_bucket)?delta:0))}document.querySelectorAll('[data-running-ms]').forEach(n=>n.textContent=durationText(Number(n.dataset.runningMs)+delta))}
setInterval(tickFlowClock,1000);
async function showTiming(id,revision){
 const x=await api(`/api/tasks/${id}/timing`);let panel=$('#flowTiming');if(!panel){panel=node('section',null,{id:'flowTiming',class:'flow-timing'});$('#taskDetail').before(panel)}
 if(!x.available){flowClock=null;panel.replaceChildren(node('p',x.message,{class:'help'}));return}
 flowClock={value:x,received:Date.now()};
 const keepOpen=panel.querySelector('details')?.open;panel.replaceChildren(node('h3','流程计时'));
 const stats=node('div',null,{class:'review-stats timing-stats'});
 for(const [key,label] of [['total_ms','总耗时'],['processing_ms','自动处理'],['human_wait_ms','人工等待'],['recovery_wait_ms','重试等待']]){const card=node('div');card.append(node('small',label),node('strong','',{ 'data-flow-clock':key}));stats.append(card)}panel.append(stats);
 if(x.partial_history)panel.append(node('p','此任务仅从本轮继续处理时开始记录，之前的阶段未补造耗时。',{class:'help'}));
 const detail=node('details');detail.open=!!keepOpen;detail.append(node('summary','阶段与每轮模型耗时'));
 const table=node('table',null,{class:'count-table'});for(const stage of x.stages){const tr=node('tr'),cell=node('td',durationText(stage.elapsed_ms));if(stage.phase===x.current_phase&&!x.ended_at)cell.setAttribute('data-running-ms',String(stage.elapsed_ms));tr.append(node('td',phases[stage.phase]||stage.phase),cell);table.append(tr)}detail.append(table);
 if(x.rounds.length){const rounds=node('table',null,{class:'count-table'}),header=node('tr');['段落组','轮次','结果','耗时'].forEach(s=>header.append(node('th',s)));rounds.append(header);for(const r of x.rounds){const tr=node('tr'),cell=node('td',durationText(r.elapsed_ms));cell.title=r.model_elapsed_ms!=null?`模型调用 ${durationText(r.model_elapsed_ms)}，校验 ${durationText(r.validation_elapsed_ms||0)}`:'本轮包括模型调用与校验';if(r.status==='running')cell.setAttribute('data-running-ms',String(r.elapsed_ms));tr.append(node('td',r.batch==='all'?'整篇合并校验':r.targets.join('、')),node('td',`${r.number} / 3`),node('td',({running:'处理中',passed:'通过',invalid:'待纠正',transport_error:'调用失败',interrupted:'已中断'})[r.status]||r.status),cell);rounds.append(tr)}detail.append(rounds,node('p','并发调用的耗时会重叠，自动处理时间按实际经过时间计算。',{class:'help'}))}
 panel.append(detail);tickFlowClock();
}

function issueList(issues){const box=node('div',null,{class:'exception-issues'});for(const issue of issues||[]){const card=node('div',null,{class:'member-card'});card.append(node('strong',issue.message||issue.code));if(issue.field_id)card.append(node('small',`字段 ${issue.field_id}${issue.block!=null?' · 段落 '+issue.block:''}`));if(issue.expected!=null||issue.actual!=null){const d=node('details');d.append(node('summary','查看期望与实际内容'));if(issue.expected!=null)d.append(node('p','期望：'+(typeof issue.expected==='string'?issue.expected:JSON.stringify(issue.expected))));if(issue.actual!=null)d.append(node('p','实际：'+(typeof issue.actual==='string'?issue.actual:JSON.stringify(issue.actual))));card.append(d)}box.append(card)}return box}

async function openTemplateExceptions(id){
 openDialog('模板异常研判');const x=await api(`/api/templates/${id}/exceptions`),body=$('#dialogBody');body.replaceChildren();
 if(!x.batches.length){body.append(node('p','当前没有待处理的模板异常。'));return}
 const drafts=new Map(x.batches.map(b=>[b.id,structuredClone(b.candidate)]));let current=x.batches[0],editorBox;
 body.append(node('p','以下批次经过三轮仍未通过。请对照原文修正候选；提交后重新校验，全部异常处理完成后才会继续。',{class:'notice'}));
 const tabs=node('div',null,{class:'review-tabs'}),view=node('div');body.append(tabs,view);
 for(const batch of x.batches)tabs.append(button('段落 '+batch.targets.join('、'),()=>{current=batch;renderBatch()}));
 function inputRow(container,label,value,onchange,textarea=false){const wrap=node('label',label.split(' · ')[0]),input=node(textarea?'textarea':'input',null,{'aria-label':label,...(textarea?{rows:'3'}:{})});input.value=value||'';input.oninput=()=>onchange(input.value);wrap.append(input);container.append(wrap);return input}
 function selectRow(container,label,value,choices,onchange){const wrap=node('label',label.split(' · ')[0]),s=node('select',null,{'aria-label':label});for(const [key,text] of choices)s.append(node('option',text,{value:key}));s.value=value||'';s.onchange=()=>onchange(s.value);wrap.append(s);container.append(wrap);return s}
 function renderBatch(){
  view.replaceChildren();const raw=drafts.get(current.id);if(!raw){view.append(node('p','没有可读取的候选，请查看调用日志。'));return}
  view.append(node('h3','本批需要修正的问题'),issueList(current.rounds.filter(r=>r.status==='invalid').at(-1)?.errors),node('p','下方「人工修正候选」是直接修改入口：修改字段含义/规则/来源或段落固定文字后，点底部「提交修正并重新校验」。',{class:'notice'}));
  const preview=node('div'),previewAction=()=>{try{preview.replaceChildren();const fields=(Array.isArray(raw.fields)?raw.fields:[]).filter(f=>f&&f.id).map(f=>({...f,sources:Array.isArray(f.sources)?f.sources:[],kind:f.kind||'text'}));const blocks=(Array.isArray(raw.blocks)?raw.blocks:[]).filter(b=>current.targets.includes(b.index)).map(b=>({...b,parts:(Array.isArray(b.parts)?b.parts:[]).filter(Boolean).map(p=>p.field?{field:p.field}:{text:p.text||''}),headers:x.sources[0].blocks.find(s=>s.index===b.index)?.rows?.[0]||[]}));renderDocument({fields,blocks},preview)}catch(e){preview.replaceChildren(node('p','预览渲染失败：'+e.message,{class:'notice'}))}};
  const p=node('details');p.open=true;p.append(node('summary','最新候选预览（带问题，尚未通过）'),button('刷新候选预览',previewAction),preview);view.append(p);previewAction();
  const history=node('details');history.append(node('summary','三轮修改与耗时'));for(const round of current.rounds){const d=node('details');d.append(node('summary',`第 ${round.number} 轮 · ${durationText(round.elapsed_ms||0)} · ${round.status==='invalid'?'未通过':round.status==='passed'?'通过':'调用记录'}`),issueList(round.errors));if(round.response){const pre=node('pre',JSON.stringify(round.response,null,2));d.append(pre)}history.append(d)}view.append(history);
  const originals=node('details');originals.append(node('summary',`${x.sources.length} 份历史报告原文`));for(const source of x.sources){const d=node('details');d.append(node('summary',source.id+' · '+source.name));for(const b of source.blocks)d.append(node('strong','段落 '+b.index),node('p',b.text));originals.append(d)}view.append(originals);
  view.append(button('仅保留本批目标段落并按原文排序',()=>{raw.blocks=current.targets.map(index=>(raw.blocks||[]).find(b=>b.index===index)).filter(Boolean);const used=new Set(raw.blocks.flatMap(b=>(b.parts||[]).map(p=>p.field).filter(Boolean)));raw.fields=(raw.fields||[]).filter(f=>used.has(f.id));renderBatch()}));
  editorBox=node('section',null,{class:'exception-editor'});editorBox.append(node('h3','人工修正候选（直接编辑）'));
  for(const f of Array.isArray(raw.fields)?raw.fields.filter(v=>v&&typeof v==='object'):[]){const card=node('details');card.append(node('summary',f.display_name||f.id));
   inputRow(card,`字段名称 · ${f.id}`,f.display_name,v=>f.display_name=v);
   inputRow(card,`字段含义 · ${f.id}`,f.semantic,v=>f.semantic=v,true);
   selectRow(card,`内容类型 · ${f.id}`,f.source_type,[['statistics','统计结果'],['materials','来源材料'],['analysis','分析文字'],['task_metadata','任务信息']],v=>f.source_type=v);
   selectRow(card,`负责填写 · ${f.id}`,f.owner,[['data','数据工具'],['writer','Writer根据证据写作']],v=>f.owner=v);
   selectRow(card,`字段结构 · ${f.id}`,f.kind,[['number','数字'],['text','文字'],['list','类别或平台列表'],['analysis','完整分析段'],['metadata','日期等信息'],['table_rows','数据表格']],v=>f.kind=v);
   inputRow(card,`取数或写作规则 · ${f.id}`,f.rule,v=>f.rule=v,true);
   inputRow(card,`展示格式 · ${f.id}`,f.format,v=>f.format=v);
   inputRow(card,`划分依据 · ${f.id}`,f.reason,v=>f.reason=v,true);
   if(f.binding){card.append(node('p','取数绑定：'+JSON.stringify(f.binding)),button('取消此字段的取数绑定',()=>{f.binding=null;renderBatch()}))}
   for(const [i,source] of (Array.isArray(f.sources)?f.sources:[]).entries()){const d=node('details');d.append(node('summary',`来源片段 ${i+1} · ${source.report_id} 段落 ${source.block}`));inputRow(d,`来源报告 · ${f.id} · ${i}`,source.report_id,v=>source.report_id=v);inputRow(d,`来源段落 · ${f.id} · ${i}`,String(source.block),v=>source.block=Number(v));inputRow(d,`来源原文 · ${f.id} · ${i}`,source.text,v=>source.text=v,true);const original=x.sources.find(s=>s.id===source.report_id)?.blocks.find(b=>b.index===source.block);if(original)d.append(node('p','对应完整原文：'+original.text,{class:'historical-example'}));card.append(d)}editorBox.append(card)
  }
  for(const b of Array.isArray(raw.blocks)?raw.blocks.filter(v=>v&&typeof v==='object'):[]){if(!current.targets.includes(b.index)||b.kind==='table')continue;const d=node('details');d.append(node('summary',`段落 ${b.index} 的固定文字`));for(const [i,part] of (b.parts||[]).entries())if(part.text!=null)inputRow(d,`固定文字 · ${b.index} · ${i}`,part.text,v=>part.text=v,true);editorBox.append(d)}
  view.append(editorBox);const advanced=node('details');advanced.append(node('summary','高级结构修正（JSON）'));const json=inputRow(advanced,'完整候选JSON',JSON.stringify(raw,null,2),()=>{},true);advanced.append(button('应用高级结构修改',()=>{drafts.set(current.id,JSON.parse(json.value));renderBatch()}));view.append(advanced);
 }
 renderBatch();const reason=node('textarea',null,{'aria-label':'人工修正说明',rows:'2'});$('#dialogActions').append(node('label','人工修正说明'),reason,button('提交修正并重新校验',async()=>{
  if(!reason.value.trim())throw Error('请填写人工修正说明。');const r=await fetch(`/api/templates/${id}/exceptions/${encodeURIComponent(current.id)}/resolve`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_revision:x.revision,input_ref:x.input_ref,candidate:drafts.get(current.id),reason:reason.value.trim()})}),data=await r.json();
  if(!r.ok){if(data.errors){$('#dialogNotice').textContent=`仍有 ${data.errors.length} 项问题，尚未放行。`;view.prepend(issueList(data.errors));return}throw Error(errors[data.detail]||data.detail||'提交未完成')}
  toast(data.remaining_batches?'本批已通过，请继续处理其他异常。':'修正已通过，正在继续模板流程。');$('#reviewDialog').close();shownRevision=null;await refresh(true);if(data.remaining_batches)await openTemplateExceptions(id)
 },true));
}
