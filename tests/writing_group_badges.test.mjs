import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

test('repeated template renders keep one relationship badge and remove stale groups',()=>{
 const source=fs.readFileSync('app/static/app.js','utf8');
 const helper=source.slice(source.indexOf('function renderWritingGroupBadges('),source.indexOf('async function openTemplate('));
 const chip={dataset:{field:'case'},title:'',badges:[],querySelector(){return this.badges[0]},append(b){b.remove=()=>this.badges.splice(this.badges.indexOf(b),1);this.badges.push(b)},removeAttribute(){this.title=''}};
 const host={querySelectorAll:()=>[chip]};
 const context=vm.createContext({node:(tag,text,attrs)=>({tag,text,...attrs})});
 vm.runInContext(helper,context);
 const groups=[{label:'案例链',members:{case:'case_facts',advice:'local_advice'}}];
 for(let i=0;i<3;i++)context.renderWritingGroupBadges(host,groups);
 assert.equal(chip.badges.length,1);
 assert.equal(chip.title,'关联组：案例链');
 context.renderWritingGroupBadges(host,[]);
 assert.equal(chip.badges.length,0);
 assert.equal(chip.title,'');
});
