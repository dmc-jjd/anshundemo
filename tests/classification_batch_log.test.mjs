import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../app/static/app.js', import.meta.url), 'utf8');
const recent = source.split('\n').find(line => line.startsWith('function recentLine('));
const details = source.split('\n').find(line => line.startsWith('async function showEvents('));

test('recent and task logs display batch counts and suppress duplicate classifier success', async () => {
  const events = [
    {type:'model_call',role:'event_classifier',status:'ok'},
    {type:'classification_batch_completed',total:45,batch_index:3,batch_total:3,batch_size:5},
    {type:'model_call',role:'event_classifier',status:'error',reason:'接口超时'},
  ];
  const rendered = [];
  const context = vm.createContext({
    phases:{},recentTools:{},api:async()=>events,
    $:()=>({children:rendered,replaceChildren(){rendered.length=0;},append(item){rendered.push(item);}}),
    node:(_tag,text)=>text,
  });
  vm.runInContext(recent+'\n'+details, context);
  context.event=events[1];
  assert.equal(vm.runInContext('recentLine(event)', context),'低置信度事件共 45 条，第 3/3 批已完成，本批 5 条');
  context.event=events[0];
  assert.equal(vm.runInContext('recentLine(event)', context),'');
  await vm.runInContext('showEvents("fixture")', context);
  assert.ok(rendered.includes('低置信度事件共 45 条，第 3/3 批已完成，本批 5 条'));
  assert.ok(rendered.some(text=>text.includes('接口超时')));
  assert.ok(!rendered.includes('模型分析完成'));
});
