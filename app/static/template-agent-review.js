/* Agent processing status is independent of the user's final confirmation. */
window.TemplateAgentReview={
  summary(section){
    if(!section?.total)return '暂无待处理意见';
    const done=section.addressed||0,remaining=section.total-done;
    if(!remaining)return `建包 agent 已处理全部 ${done} 项 · 待你审阅，模板尚未确认`;
    return `建包 agent 已处理 ${done}/${section.total} 项 · 仍有 ${remaining} 项待处理或待你判断`;
  },
  banner(section){
    const p=document.createElement('p');p.className='template-agent-review-status';
    p.dataset.complete=String(Boolean(section?.total&&section.addressed===section.total));
    p.setAttribute('role','status');p.textContent=this.summary(section);return p;
  },
  item(record){
    const p=document.createElement('p');p.className='template-agent-review-item';
    const labels={addressed:'建包 agent 已处理 · 待你审阅',needs_user:'待你判断',pending:'待处理',stale:'模板已变化 · 处理记录待复核'};
    p.textContent=(labels[record?.status]||'待处理')+(record?.note?'：'+record.note:'');return p;
  }
};
