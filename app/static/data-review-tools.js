let reviewSaveSequence=0;
function renderMoveTargetPicker(container,d,g,collection){
 const kind=d.tab==='themes'?'分类':'事件',choice={value:''},section=node('section',null,{class:'move-target-picker'});
 const toggle=button(`选择移入目标${kind}`,()=>{panel.hidden=!panel.hidden;if(!panel.hidden)search.focus()});
 const panel=node('div',null,{class:'move-target-panel'});panel.hidden=true;
 const search=node('input',null,{type:'search',placeholder:`搜索目标${kind}的标题或内容`,'aria-label':`搜索目标${kind}`}),list=node('div',null,{class:'move-target-results'}),preview=node('div',null,{class:'move-target-preview'});
 const options=collection.map((other,index)=>({other,index})).filter(x=>x.other!==g);
 const draw=()=>{const query=search.value.trim().toLowerCase(),matches=options.filter(({other})=>!query||`${other.title||other.candidate_theme} ${d.records[other.representative_id]?.summary||''}`.toLowerCase().includes(query));list.replaceChildren(node('p',`共 ${matches.length} 个目标${kind}，显示前 ${Math.min(matches.length,40)} 个；可输入关键词缩小范围。`,{class:'help'}));
  for(const {other,index} of matches.slice(0,40)){const title=other.title||other.candidate_theme;const select=button(`${title}（${other.member_ids.length} 条记录）`,()=>{choice.value=String(index);toggle.textContent=`更换目标${kind}`;panel.hidden=true;preview.replaceChildren(node('strong',`已选择目标${kind}：${title}`),node('p',`${other.member_ids.length} 条来源记录；下方可以查看内容，尚未移动记录。`,{class:'help'}));
    const details=node('details');details.append(node('summary',`查看目标${kind}全部记录`));let shown=0;const cards=node('div',null,{class:'move-preview-members'}),more=button('继续查看记录',load);
    function load(){for(const id of other.member_ids.slice(shown,shown+20)){const r=d.records[id];if(!r)continue;const card=node('div',null,{class:'member-card'});card.append(node('strong',r.title),node('p',`${r.published||''} · ${r.source||''}`,{class:'help'}),node('p',r.summary||'没有原文梗概'));cards.append(card)}shown+=20;more.hidden=shown>=other.member_ids.length}
    load();details.append(cards,more);preview.append(details);
  });select.className='move-target-option';list.append(select)}
  if(!matches.length)list.append(node('p',`没有匹配的目标${kind}，请更换搜索词。`));
 };search.oninput=draw;draw();panel.append(search,list);section.append(node('strong',`将勾选记录移入其他${kind}`),node('p',`这里列出其他现有${kind}。先选择并查看目标，再勾选来源记录执行移动。`,{class:'help'}),toggle,panel,preview);container.append(section);return choice;
}
function reviewDraftPayload(d){return {groups:d.groups,themes:d.themes,merge_decisions:d.mergeDecisions,briefs:d.briefPatches,groups_dirty:d.groupsDirty}}
function createDataEditor(data,id){
 const saved=data.review_draft||{},d={...data,id,tab:'events',page:0,query:'',selected:null,
  groups:structuredClone(saved.groups||data.event_groups),themes:structuredClone(saved.themes||data.themes),
  mergeDecisions:structuredClone(saved.merge_decisions||data.human_merge_decisions||{}),briefPatches:structuredClone(saved.briefs||{}),groupsDirty:!!saved.groups_dirty,
  pendingOnly:true,draftVersion:data.draft_version||0,saveStatus:data.review_draft?'已恢复服务器保存的审核草稿':'尚未修改'};
 d.savedSignature=JSON.stringify(reviewDraftPayload(d));
 if(!d.frozen&&!d.analysis_pending){try{const local=JSON.parse(localStorage.getItem('report-review-draft:'+id)||'null');
  if(local&&local.analysis_ref===d.analysis_ref&&local.revision===d.revision&&(!data.draft_saved_at||local.saved_at>data.draft_saved_at)){
   d.groups=local.data.groups;d.themes=local.data.themes;d.mergeDecisions=local.data.merge_decisions;d.briefPatches=local.data.briefs;d.groupsDirty=local.data.groups_dirty;d.saveStatus='已恢复本地未提交的审核修改';
  }
 }catch{d.saveStatus='本地备份无法读取，已载入服务器草稿'}}
 return d;
}
function updateReviewSaveLabel(d){const label=$('#reviewSaveStatus');if(label&&d===dataEditor)label.textContent=d.saveStatus}
function scheduleReviewSave(d){
 if(d.frozen||d.analysis_pending||!d.analysis_ref)return;const payload=reviewDraftPayload(d),signature=JSON.stringify(payload);
 if(signature===d.savedSignature)return;
 try{localStorage.setItem('report-review-draft:'+d.id,JSON.stringify({analysis_ref:d.analysis_ref,revision:d.revision,data:payload,saved_at:new Date().toISOString()}))}catch{}
 d.saveStatus='修改已暂存，正在保存草稿…';updateReviewSaveLabel(d);clearTimeout(d.saveTimer);
 d.saveTimer=setTimeout(()=>flushReviewDraft(d).catch(e=>{d.saveStatus='草稿尚未保存到服务器：'+e.message;updateReviewSaveLabel(d)}),300);
}
async function flushReviewDraft(d){
 clearTimeout(d.saveTimer);if(d.frozen||d.analysis_pending)return;
 if(d.saveFlight){await d.saveFlight;return flushReviewDraft(d)}
 const payload=structuredClone(reviewDraftPayload(d)),signature=JSON.stringify(payload);if(signature===d.savedSignature)return;
 d.saveStatus='正在保存草稿…';updateReviewSaveLabel(d);
 d.saveFlight=api(`/api/tasks/${d.id}/review-draft`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_revision:d.revision,analysis_ref:d.analysis_ref,expected_version:d.draftVersion,data:payload})}).then(result=>{
  d.draftVersion=result.version;d.savedSignature=signature;d.saveStatus=`已保存草稿 · ${Object.keys(d.mergeDecisions).length} 项事件判断`;
  try{localStorage.setItem('report-review-draft:'+d.id,JSON.stringify({analysis_ref:d.analysis_ref,revision:d.revision,data:payload,saved_at:result.updated_at}))}catch{}
  updateReviewSaveLabel(d);
 }).finally(()=>{d.saveFlight=null});
 await d.saveFlight;if(JSON.stringify(reviewDraftPayload(d))!==d.savedSignature)await flushReviewDraft(d);
}
function reviewGate(d){
 const position=new Map(d.groups.flatMap((g,i)=>g.member_ids.map(id=>[id,i]))),cases=d.merge_ambiguities||[];
 const pending=cases.filter(c=>!d.mergeDecisions[c.id]);
 const conflicts=cases.filter(c=>d.mergeDecisions[c.id]&&((position.get(c.source_id)===position.get(c.target_id))!==(d.mergeDecisions[c.id]==='same')));
 const unknown=new Set(d.themes.filter(g=>['待人工分类','模型尚未处理'].includes(g.candidate_theme)).flatMap(g=>g.member_ids));
 const unclassified=d.groups.filter(g=>g.member_ids.some(id=>unknown.has(id)));
 const briefs=(d.top10||[]).filter(row=>{const brief=d.briefPatches[row.fingerprint]||row,n=[...(brief.summary||'').trim()].length;return brief.status!=='complete'||n<15||n>35});
 return {pending,conflicts,unclassified,briefs,ready:!pending.length&&!conflicts.length&&!unclassified.length&&!briefs.length&&!d.groupsDirty};
}
function assignEventCategory(d,eventId,category){
 if(!category.trim()||['待人工分类','模型尚未处理'].includes(category))throw Error('请选择明确的事件分类。');
 const event=d.groups.find(g=>g.id===eventId);if(!event)throw Error('事件已更新，请重新选择。');
 const ids=new Set(event.member_ids);for(const theme of d.themes)theme.member_ids=theme.member_ids.filter(id=>!ids.has(id));
 let target=d.themes.find(g=>g.candidate_theme===category);if(!target){target={candidate_theme:category,member_ids:[]};d.themes.push(target)}
 target.member_ids.push(...ids);normalizeGroups(d);
}
function locatePendingRelationship(d){d.tab='ambiguities';d.pendingOnly=true;d.selected=null;renderData();$('#dialogBody').scrollTop=0;$('#dialogNotice').textContent='这里只显示未完成或与分组冲突的关系，已完成项已隐藏。'}
async function refreshReviewAnalysis(d){
 const gate=reviewGate(d);await flushReviewDraft(d);
 if(gate.pending.length||gate.conflicts.length){locatePendingRelationship(d);throw Error(`草稿已保存。还有 ${gate.pending.length} 项关系未判断、${gate.conflicts.length} 项与分组冲突，请处理后更新。`)}
 await post(`/api/tasks/${d.id}/event-settings`,{expected_revision:d.revision,groups:d.groups,themes:d.themes,merge_decisions:d.mergeDecisions,briefs:d.briefPatches,draft_version:d.draftVersion});
 shownRevision=null;toast('人工判断已直接生效，统计和排名已重算；没有调用模型。');await openData(d.id);if(reviewGate(dataEditor).unclassified.length){dataEditor.tab='classification_pending';dataEditor.query='';dataEditor.page=0;renderData()}else if(reviewGate(dataEditor).briefs.length){dataEditor.tab='top10';renderData()}$('#dialogBody').scrollTop=0;
}
function renderReviewGate(){
 const d=dataEditor,b=$('#confirmDataAction');if(!d||!b)return;const gate=reviewGate(d);
 b.disabled=!gate.ready;
 const reasons=[];if(gate.pending.length)reasons.push(`${gate.pending.length} 项关系未判断`);if(gate.conflicts.length)reasons.push(`${gate.conflicts.length} 项关系与分组冲突`);if(d.groupsDirty)reasons.push('人工分组尚未应用，需同步统计和排名（不调用模型）');if(gate.unclassified.length)reasons.push(`${gate.unclassified.length} 个事件待分类`);if(gate.briefs.length)reasons.push(`${gate.briefs.length} 条梗概待补充`);
 b.title=reasons.join('；');let notice=$('#dataGateNotice');if(!notice){notice=node('p',null,{id:'dataGateNotice',class:'help'});$('#dialogActions').prepend(notice)}
 const done=(d.merge_ambiguities||[]).length-gate.pending.length;
 notice.textContent=`事件关系已判断 ${done}/${(d.merge_ambiguities||[]).length}。`+(gate.ready?'审核项已完成，可以锁定数据。':reasons.join('；'));
 let next=$('#dataNextAction');if(next)next.remove();if(gate.ready)return;
 let text,action;
 if(gate.pending.length||gate.conflicts.length){text='定位未完成的事件关系';action=()=>locatePendingRelationship(d)}
 else if(d.groupsDirty){text='应用人工判断并进入下一步';action=()=>refreshReviewAnalysis(d)}
 else if(gate.unclassified.length){text=`处理待分类事件（${gate.unclassified.length}）`;action=()=>{d.tab='classification_pending';d.query='';d.page=0;d.selected=null;renderData();$('#dialogBody').scrollTop=0}}
 else{text=`补充事件梗概（${gate.briefs.length}）`;action=()=>{d.tab='top10';renderData();$('#dialogBody').scrollTop=0}}
 next=button(text,action,true);next.id='dataNextAction';b.before(next);
}
function renderPendingCategoryControls(container,d,g){
 if(d.frozen||d.analysis_pending)return;
 const row=node('section',null,{class:'event-category-controls'}),known=[...new Set(d.themes.map(t=>t.candidate_theme).filter(c=>!['待人工分类','模型尚未处理'].includes(c)))];
 const select=node('select',null,{'aria-label':'此事件的分类'});select.append(node('option','请选择此事件的分类',{value:''}));for(const name of [...new Set([...known,'其他'])])select.append(node('option',name,{value:name}));
 const custom=node('input',null,{'aria-label':'自定义事件分类',placeholder:'或填写自定义分类'});
 row.append(node('strong','按整个事件分类'),node('p','事件关系决定哪些记录属于同一件事。合并后原分类一致就沿用；原分类冲突或尚无明确分类时，需要在这里补选最终分类，不再交回模型。',{class:'help'}),select,custom,button('应用此事件分类',()=>{assignEventCategory(d,g.id,custom.value.trim()||select.value);d.selected=null;renderData();toast('本事件全部来源已归入指定分类，正在保存草稿。')}));container.append(row);
}

async function finishRelationshipChoice(d){renderData();if(!reviewGate(d).pending.length&&!reviewGate(d).conflicts.length){await refreshReviewAnalysis(d)}}
