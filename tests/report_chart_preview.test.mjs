import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

test('chart wrapper forwards chart URLs to both report preview entry points',()=>{
 const source=fs.readFileSync('app/static/insights.js','utf8');
 const wrapper=source.slice(source.indexOf('const renderDocumentBeforeCharts='),source.indexOf('const structuredControlsBeforeCharts='));
 const calls=[],context=vm.createContext({renderDocument:(...args)=>calls.push(args),editField(){}});
 vm.runInContext(wrapper,context);
 const urls={daily:'/api/tasks/current/charts/daily'};
 for(const entry of ['draft','writing-review'])context.renderDocument({charts:[]},{entry},{},null,urls);
 assert.equal(calls.length,2);
 calls.forEach(args=>assert.equal(args[4],urls));
});
