// Report metadata is supplied before processing; this module never calls a model.
errors.report_parameters_not_editable='当前阶段正在处理或已终审，暂不能修改报告参数。';
let suggestionSequence=0,issueEdited=false,dateEdited=false;
const reportIssue=document.querySelector('#reportIssue'),reportDate=document.querySelector('#reportDate');
reportIssue.addEventListener('input',()=>issueEdited=true);reportDate.addEventListener('input',()=>dateEdited=true);
async function refreshParameterSuggestions(){
 const month=$('#reportMonth').value,template=$('#reportTemplate').value;if(!month||!template)return;
 const sequence=++suggestionSequence;
 try{const result=await api('/api/report-parameter-suggestions?'+new URLSearchParams({template_ref:template,report_month:month}));if(sequence!==suggestionSequence)return;
  if(!issueEdited)reportIssue.value=result.issue_number??'';if(!dateEdited)reportDate.value=result.publication_date;
  $('#parameterSuggestion').textContent=result.issue_reason+' '+result.publication_reason;
 }catch(e){$('#parameterSuggestion').textContent='自动识别暂不可用，请填写实际期号和成文日期。'}
}
$('#reportMonth').addEventListener('change',()=>{issueEdited=false;refreshParameterSuggestions()});$('#reportTemplate').addEventListener('change',()=>{issueEdited=false;refreshParameterSuggestions()});
const todayParts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()).filter(p=>p.type!=='literal').map(p=>[p.type,p.value]));
reportDate.value=`${todayParts.year}-${todayParts.month}-${todayParts.day}`;
$('#parameterSuggestion').textContent='选择模板后识别期号；成文日期默认今天，可修改。';
const startReportWithParameters=$('#startReport').onclick;
$('#startReport').onclick=()=>{if(!reportIssue.value||Number(reportIssue.value)<1||!reportDate.value){toast('请先核对并填写本期报告期号和成文日期。');return}return startReportWithParameters()};

async function openReportParameters(id){
 openDialog('报告参数（可在数据处理阶段填写）');const body=$('#dialogBody');body.textContent='正在读取报告参数…';
 const state=await api(`/api/tasks/${id}`),saved=state.metadata.report_parameters||{};
 const draftHash=state.draft_ref?(await api(`/api/tasks/${id}/draft-view`)).draft.content_hash:null;
 const suggested=await api('/api/report-parameter-suggestions?'+new URLSearchParams({template_ref:state.template_ref,report_month:state.metadata.report_month})).catch(()=>({issue_reason:'请填写实际期号。',publication_reason:'请填写实际成文日期。'}));
 const issue=node('input',null,{type:'number',min:'1',value:String(saved.issue_number??suggested.issue_number??''),'aria-label':'本期报告期号'}),day=node('input',null,{type:'date',value:saved.publication_date||suggested.publication_date||reportDate.value,'aria-label':'本期成文日期'});
 const il=node('label','报告期号'),dl=node('label','成文日期（自动拆分为成文月份、日期日）');il.append(issue);dl.append(day);
 body.replaceChildren(node('p','这些是本期报告参数，保存后直接计算对应字段，不重新调用模型。',{class:'help'}),il,dl,node('p',suggested.issue_reason+' '+suggested.publication_reason,{class:'help'}));
 $('#dialogActions').append(button('保存报告参数',async()=>{if(!issue.value||Number(issue.value)<1||!day.value)throw Error('请填写有效的期号和成文日期。');
  await post(`/api/tasks/${id}/report-parameters`,{expected_revision:state.revision,expected_hash:draftHash,issue_number:Number(issue.value),publication_date:day.value});
  toast('报告参数已保存，未调用模型。');$('#reviewDialog').close();shownRevision=null;await refresh(true);
 },true));
}
const detailBeforeReportParameters=detail;
detail=async function(id,force=false){await detailBeforeReportParameters(id,force);const state=await api(`/api/tasks/${id}`);
 if(state.kind!=='report'||!['awaiting_review','facts_frozen','awaiting_final_review','failed','analysis_pending'].includes(state.phase))return;
 if(!document.querySelector('#reportParametersAction')){const action=button('报告参数：期号与成文日期',()=>openReportParameters(id));action.id='reportParametersAction';$('#taskActions').prepend(action)}
};
