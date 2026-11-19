/* Template review: visible, editable relationships; confirmed templates stay read-only. */
window.WritingGroups = (() => {
  const roles={topic:'主题',background:'背景',details:'细节条目',case_facts:'案例事实',case_analysis:'案例分析',local_advice:'本地建议',title_list:'标题列表',selected_title:'重点标题',propagation_count:'传播条数',overview_examples:'综述举例',sensitive_examples:'敏感举例',organization_total:'机构总数',article_total:'报道总数',central_organizations:'央级机构数',central_articles:'央级报道数',provincial_organizations:'省级机构数',provincial_articles:'省级报道数',local_organizations:'地方机构数',local_articles:'地方报道数',central_examples:'央级媒体示例',provincial_examples:'省级媒体示例',local_examples:'地方媒体示例',comparison:'层级比较表述',other:'关联字段'};
  const el=(tag,text)=>{const n=document.createElement(tag);if(text)n.textContent=text;return n;};
  function mount(host,{fields,groups=[],readonly=false,onSave,onField,note=""}) {
    host.replaceChildren();let draft=structuredClone(groups);
    const status=el('p');status.role='status';
    const draw=()=>{
      host.replaceChildren();host.append(el('h3','字段关联组'));if(note)host.append(el('p',note));
      host.append(el('p',readonly?'以下为写作时共同使用的上下文与口径，已确认模板只读。':'将同一主题或案例的字段放入一组，写作与审核共同使用。保存关联关系不会确认模板。'));
      for(const [index,group] of draft.entries()) {
        const card=el('fieldset');card.className='writing-group-card';
        const title=el('input');title.value=group.label||'';title.placeholder='关联组名称';title.setAttribute('aria-label','关联组名称');title.disabled=readonly;
        title.oninput=()=>group.label=title.value;card.append(title);
        const instruction=el('textarea');instruction.rows=3;instruction.value=group.instruction||'';instruction.placeholder='共同主题、材料范围和一致性要求';instruction.setAttribute('aria-label','关联组写作要求');instruction.disabled=readonly;
        instruction.oninput=()=>group.instruction=instruction.value;card.append(instruction);
        const members=el('div');members.className='writing-group-members';
        for(const field of fields.filter(f=>!readonly||Object.hasOwn(group.members,f.id))) {
          const row=el('div');const label=el('label');const check=el('input');check.type='checkbox';check.checked=Object.hasOwn(group.members,field.id);check.disabled=readonly;
          label.append(check,document.createTextNode(field.display_name||field.id));row.append(label);
          const role=el('select');const choices={...roles};const current=group.members[field.id];if(current&&!choices[current])choices[current]=current;
          for(const [value,name] of Object.entries(choices)){const option=el('option',name);option.value=value;role.append(option);}
          role.value=current||'other';role.disabled=readonly||!check.checked;role.setAttribute('aria-label',(field.display_name||field.id)+'的组内角色');
          role.onchange=()=>{group.members[field.id]=role.value;};
          check.onchange=()=>{if(check.checked)group.members[field.id]=role.value;else delete group.members[field.id];role.disabled=!check.checked;};row.append(role);
          const locate=el('button','查看字段');locate.type='button';locate.className='btn ghost sm';locate.onclick=()=>onField?.(field);row.append(locate);members.append(row);
        }
        card.append(members);
        if(!readonly){const remove=el('button','移除此组');remove.type='button';remove.className='btn ghost';remove.onclick=()=>{draft.splice(index,1);draw();};card.append(remove);}
        host.append(card);
      }
      if(!readonly){
        const add=el('button','新增关联组');add.type='button';add.className='btn ghost';add.onclick=()=>{draft.push({id:crypto.randomUUID(),label:'新关联组',members:{},instruction:'',query:{focus:'all',limit:10}});draw();};
        const save=el('button','保存字段关联');save.type='button';save.className='btn primary';save.onclick=async()=>{save.disabled=true;try{await onSave(draft);status.textContent='关联关系已保存，模板待你亲自确认。';}catch(e){status.textContent=e.message;}finally{save.disabled=false;}};
        host.append(add,save);
      }
      host.append(status);
    };draw();
  }
  return {mount};
})();
