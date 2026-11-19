const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('app/static/data-review-tools.js','utf8');
const app=fs.readFileSync('app/static/app.js','utf8');
const normalize=app.split('\n').find(line=>line.startsWith('function normalizeGroups('));
const ctx=vm.createContext({structuredClone,localStorage:{getItem:()=>null},console});
vm.runInContext(source+'\n'+normalize,ctx);
vm.runInContext(`
const data={event_groups:[],themes:[{candidate_theme:'待人工分类',member_ids:['a','b']},
 {candidate_theme:'教育管理',member_ids:['c']}],records:{a:{title:'同一标题'},b:{title:'同一标题'},c:{title:'学校招生'}},
 method:{disabled:true},top10:[],merge_ambiguities:[],frozen:false,analysis_pending:false};
globalThis.d=createDataEditor(data,'test');
`,ctx);
let gate=vm.runInContext('reviewGate(d)',ctx);
assert.equal(gate.unclassified.length,2,'Two unknown records must be pending when no event groups exist');
assert.equal(gate.ready,false,'Unknown records must block confirmation');
assert.equal(gate.unclassified[0].title,'同一标题');
assert.notEqual(gate.unclassified[0].id,gate.unclassified[1].id,'Equal titles must remain separate');
ctx.itemId=gate.unclassified[0].id;
vm.runInContext("assignEventCategory(d,itemId,'社会民生')",ctx);
gate=vm.runInContext('reviewGate(d)',ctx);
assert.equal(gate.unclassified.length,1);
assert.equal(vm.runInContext('d.groups.length',ctx),0,'Display entries must not become dedup groups');
ctx.itemId=gate.unclassified[0].id;
vm.runInContext("assignEventCategory(d,itemId,'社会民生')",ctx);
assert.equal(vm.runInContext('reviewGate(d).ready',ctx),true);
assert.equal(vm.runInContext('reviewDraftPayload(d).groups.length',ctx),0);
vm.runInContext(`d.groups=[{id:'g',title:'归并事件',representative_id:'a',member_ids:['a','b']}];
 d.method.disabled=false;d.themes=[{candidate_theme:'待人工分类',member_ids:['a','b']},{candidate_theme:'教育管理',member_ids:['c']}];`,ctx);
assert.equal(vm.runInContext('reviewGate(d).unclassified.length',ctx),1);
vm.runInContext("assignEventCategory(d,'g','社会民生')",ctx);
assert.equal(vm.runInContext('reviewGate(d).ready',ctx),true,'Dedup-enabled events retain whole-event assignment');
console.log('record and event classification verified');
