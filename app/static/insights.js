// Presentation controls and measured model usage. All corrections save locally.
Object.assign(errors,{stale_draft_hash:'稿件已更新，请重新打开报告后再保存。',report_not_editable_in_current_phase:'当前阶段不能修改报告，请等待写作结束后操作。',reference_comparison_stale:'数据版本已变化，请重新进行参考数据对账。'});
phases.writing_validation='写作验证';
const chartStyleLabels={pie:'饼图',line:'折线图',bar:'纵向柱状图',barh:'横向条形图'};
const chartAllowed={daily:['line','bar'],sentiment:['pie','bar','barh'],platform:['pie','bar','barh'],theme:['pie','bar','barh'],locality:['pie','bar','barh']};
function chartIcon(style){
 const shapes={pie:'<circle cx="48" cy="45" r="30" fill="#5b9bd5"/><path d="M48 45V15A30 30 0 0 1 78 45Z" fill="#ed7d31"/>',line:'<path d="M15 72H90M15 72V15" stroke="#789" fill="none"/><path d="M20 60L40 38L57 48L76 23L90 32" fill="none" stroke="#16748c" stroke-width="4"/>',bar:'<path d="M15 72H90M15 72V15" stroke="#789" fill="none"/><path d="M24 72V47H38V72M47 72V25H61V72M70 72V38H84V72" fill="#16748c"/>',barh:'<path d="M15 72H90M15 72V15" stroke="#789" fill="none"/><path d="M15 23H69V36H15M15 43H87V56H15M15 63H45V72H15" fill="#16748c"/>'};
 return node('img',null,{src:'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 105 90">${shapes[style]||shapes.bar}</svg>`),alt:chartStyleLabels[style]||style,class:'chart-style-icon'});
}
function chartStyleEditor(charts,container,onChange,templateTask=null){
 const grid=node('section',null,{class:'chart-settings-grid'});
 for(const chart of charts||[]){const card=node('div',null,{class:'chart-setting-card'}),icon=node('div'),select=node('select',null,{'aria-label':chart.title+'图表样式'});
  icon.append(chartIcon(chart.style));card.append(node('strong',`图${chart.drawing_index} ${chart.title}`),icon);
  (chartAllowed[chart.id]||['bar','barh','pie']).forEach(style=>select.append(node('option',chartStyleLabels[style],{value:style})));select.value=chart.style;
  const axis=node('p',null,{class:'help'});const describe=()=>{axis.textContent=select.value==='pie'?'按同一统计范围显示数量与占比':select.value==='barh'?'横轴：数量；纵轴：类别':select.value==='line'?'横轴：日期；纵轴：数量':'横轴：类别；纵轴：数量'};describe();
  select.onchange=()=>{icon.replaceChildren(chartIcon(select.value));chart.style=select.value;describe();onChange(chart.id,select.value)};card.append(select,axis);
  if(templateTask){const d=node('details'),image=node('img',null,{src:`/api/templates/${templateTask}/charts/${chart.id}/source`,alt:'历史报告原图：'+chart.title,loading:'lazy',style:'width:100%;height:auto'});image.onerror=()=>image.replaceWith(node('p','该来源图暂不能预览；上方仍可设置样式。',{class:'help'}));d.append(node('summary','对照历史报告原图'),image);card.append(d)}
  grid.append(card)
 }container.append(grid)
}
const renderDocumentBeforeCharts=renderDocument;
renderDocument=function(definition,container,values=null,onField=null){
 if(values===null&&onField===editField&&templateEditor){const editor=templateEditor;editor.chartStyles=Object.fromEntries((definition.charts||[]).map(c=>[c.id,c.style]));
  container.append(node('h3','图表样式'));chartStyleEditor(definition.charts,container,(kind,style)=>{editor.chartStyles[kind]=style;editor.chartStylesDirty=true},editor.id);
  if(editor.confirmed)container.append(button('另存图表样式版本',async()=>{await post(`/api/templates/${editor.id}/chart-version`,{expected_revision:editor.revision,styles:editor.chartStyles});toast('已保存新样式版本，原版本与已有报告保留。');await refresh();await openTemplate(editor.id)}));
  else container.append(node('p','图表样式会随“确认并保存模板”一起保存。',{class:'help'}))
 }renderDocumentBeforeCharts(definition,container,values,onField)
};
const structuredControlsBeforeCharts=structuredDraftControls;
structuredDraftControls=function(id,x,body){
 const history=node('details');history.append(node('summary','第二部分：风险选题依据与前瞻窗口'));body.append(history);
 api(`/api/tasks/${id}/historical-research`).then(r=>{history.append(node('p',`实际联网记录：成功搜索 ${r.web_summary?.search||0} 次，阅读原文 ${r.web_summary?.fetch||0} 次。`,{class:'help'}));if(r.status!=='ready')history.append(node('p','已进行联网检索，但合格依据仍不足。可比较历史、季节与地方活动等依据；需查看具体缺口和已经比较的候选。',{class:'notice'}));if(r.skipped_pages?.length){const skipped=node('details');skipped.append(node('summary',`已自动跳过 ${r.skipped_pages.length} 个不可读来源`));for(const source of r.skipped_pages)skipped.append(node('p',source.reason),node('a',source.url,{href:source.url,target:'_blank',rel:'noopener noreferrer'}));history.append(skipped)}if(r.read_pages?.length){const pages=node('details');pages.append(node('summary',`查看已阅读的 ${r.read_pages.length} 篇资料（不代表均通过校验）`));for(const p of r.read_pages)pages.append(node('p'),node('a',p.title||p.url,{href:p.url,target:'_blank',rel:'noopener noreferrer'}));history.append(pages)}history.append(node('p',`前瞻窗口：${r.window.label}；${r.status==='ready'?'已核实选题':'依据仍有缺口'}`));if(r.candidate_comparison?.candidates){const compared=node('details');compared.append(node('summary',`查看比较过的 ${r.candidate_comparison.candidates.length} 类候选`));for(const c of r.candidate_comparison.candidates)compared.append(node('h4',c.category),node('p',c.comparison_reason),node('p',c.knowledge_basis,{class:'help'}));history.append(compared)}for(const topic of r.topics){history.append(node('h4',topic.category),node('p',topic.basis_label||'历史依据',{class:'help'}),node('p',topic.rationale));if(topic.knowledge_ref)history.append(node('p',topic.knowledge_basis,{class:'help'}));for(const c of topic.evidence)history.append(node('a',`${c.period} · ${c.title}`,{href:c.url,target:'_blank',rel:'noopener noreferrer'}),node('p',c.quote,{class:'help'}))}if(r.errors.length)history.append(node('p',r.status==='ready'?`已剔除 ${r.errors.length} 项不合要求的候选；有效依据见上。`:r.errors.join('；'),{class:'help'}))}).catch(()=>history.append(node('p','第二部分先用模型知识比较5—8类候选，目标5类合格选题，按需核实地方事实，输出4—5条月度工作建议。',{class:'help'})));
 const comparison=node('div');body.append(comparison);api(`/api/tasks/${id}/reference-comparison`).then(r=>{
  comparison.append(node('p',`统计口径核对：当前 ${r.current_group_count} 组包含 ${r.groups_without_warning} 组未预警事件；限定预警后为 ${r.groups_with_warning} 组。参考去重文件为 ${r.reference_rows} 条。差异涉及归并粒度，尚未替换冻结事实。`,{class:'notice'}),node('a','查看817条与当前事件的逐行比对明细',{href:`/api/tasks/${id}/reference-comparison?details=true`,target:'_blank'}))
 }).catch(()=>{});
 const changes={};body.append(node('h3','更换本期图表样式'));
 chartStyleEditor(x.definition.charts,body,(kind,style)=>changes[kind]=style);
 body.append(button('只更新图表，保留报告文字',async()=>{if([...body.querySelectorAll('textarea')].some(t=>t.value.trim()))throw Error('请先保存已填写的文字，再更换图表。');await post(`/api/tasks/${id}/chart-settings`,{expected_hash:x.draft.content_hash,styles:changes});toast('图表已更新，未调用模型。');await openDraft(id);await refresh()}));
 structuredControlsBeforeCharts(id,x,body)
};
function money(low,high){const f=n=>'¥'+n.toFixed(6);return Math.abs(low-high)<1e-9?f(low):f(low)+'～'+f(high)}
async function showTokenUsage(id){
 let panel=$('#tokenUsage');if(!panel){panel=node('section',null,{id:'tokenUsage',class:'usage-panel'});$('#taskDetail').append(panel)}
 try{const x=await api(`/api/tasks/${id}/usage`);panel.replaceChildren(node('h3','Token 用量与费用估算'));
  const stats=node('div',null,{class:'usage-stats'});[['输入 Token',x.input_tokens],['输出 Token',x.output_tokens],['合计 Token',x.total_tokens],['可计价部分',money(x.estimated_cost_min,x.estimated_cost_max)]].forEach(([name,value])=>{const d=node('div');d.append(node('small',name),node('strong',typeof value==='number'?value.toLocaleString():value));stats.append(d)});panel.append(stats);
  panel.append(node('p',`已记录 ${x.requests} 次响应，缓存命中 ${x.cache_hit_tokens.toLocaleString()} Token。${x.unpriced_requests} 次响应待明确价格；${x.unmetered_requests} 次请求缺少用量。`,{class:'help'}));
  if(x.web_successful_requests)panel.append(node('p',`联网搜索 ${x.web_successful_requests.search} 次、阅读 ${x.web_successful_requests.fetch} 次，联网费用估算 ¥${x.estimated_web_cost.toFixed(6)}（已含在上方可计价部分）。`,{class:'help'}));
  const details=node('details');details.append(node('summary','按角色、阶段与模型查看'));const table=node('table'),header=node('tr');['角色 / 阶段','模型','响应数','输入','输出','估算费用'].forEach(t=>header.append(node('th',t)));table.append(header);x.rows.forEach(row=>{const tr=node('tr');[row.role+' / '+(phases[row.phase]||row.phase),row.model,row.requests,row.input_tokens,row.output_tokens,row.unpriced_requests===row.requests?'待定':money(row.cost_min,row.cost_max)+(row.unpriced_requests?'（部分）':'')].forEach(v=>tr.append(node('td',String(v))));table.append(tr)});details.append(table,node('p',x.note,{class:'help'}));panel.append(details,button('设置估算单价',openTokenPricing));
 }catch(e){panel.replaceChildren(node('p','Token监测暂不可用：'+e.message,{class:'help'}))}
}
const detailBeforeUsage=detail;
detail=async function(id,force=false){await detailBeforeUsage(id,force);await showTokenUsage(id)};
async function openTokenPricing(){
 const config=await api('/api/token-pricing');openDialog('Token费用估算设置');const body=$('#dialogBody');body.append(node('p','单位：元 / 百万Token。用于本地估算，不修改模型服务商账单；价格变化后可在这里调整。'));
 const mode=node('select',null,{'aria-label':'估算计价时段'});[['auto','按请求时间自动估算（北京时间）'],['off_peak','全部按空闲时段估算'],['peak','全部按高峰时段估算']].forEach(([v,t])=>mode.append(node('option',t,{value:v})));mode.value=config.mode;body.append(mode);
 const historical=node('select',null,{'aria-label':'历史未标明模型的估算依据'});historical.append(node('option','历史模型未知：保留费用待定',{value:''}));Object.keys(config.models).forEach(model=>historical.append(node('option','明确按 '+model+' 单价估算历史未知调用',{value:model})));historical.value=config.historical_model||'';historical.onchange=()=>config.historical_model=historical.value||null;body.append(node('label','历史未标明模型的调用'),historical);
 for(const kind of ['search','fetch']){const label=node('label',(kind==='search'?'联网搜索':'网页阅读')+'单价（元/千次成功请求）'),input=node('input',null,{type:'number',min:'0',step:'.1',value:String(config.web_per_1000?.[kind]??5)});config.web_per_1000||={search:5,fetch:5};input.oninput=()=>config.web_per_1000[kind]=Number(input.value);label.append(input);body.append(label)}
 for(const [model,rates] of Object.entries(config.models)){body.append(node('h3',model));for(const [bandName,values] of Object.entries(rates)){body.append(node('h4',bandName==='peak'?'高峰时段':'空闲时段'));for(const [kind,value] of Object.entries(values)){const label=node('label',({cached_input:'缓存命中输入',input:'未命中输入',output:'输出'})[kind]),input=node('input',null,{type:'number',min:'0',step:'.001',value:String(value),'aria-label':`${model} ${bandName} ${kind}`});input.oninput=()=>rates[bandName][kind]=Number(input.value);label.append(input);body.append(label)}}}
 body.append(node('a','核对 DeepSeek 官方价格',{href:config.source,target:'_blank',rel:'noopener noreferrer'}),node('p','自动模式下，工作日高峰若没有法定节假日日历，会显示费用区间；未知模型不猜价格。',{class:'help'}));
 $('#dialogActions').append(button('保存估算设置',async()=>{config.mode=mode.value;await api('/api/token-pricing',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(config)});$('#reviewDialog').close();toast('估算设置已保存。');if(selected)await showTokenUsage(selected)},true))
}
