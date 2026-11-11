// Read-only real draft evidence, followed by page-local simulated group choices.
const {chromium}=require('../data/ui-check/node_modules/playwright-core');
const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Users/57676/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe',headless:true});try{
 const page=await browser.newPage({viewport:{width:1432,height:964}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto((process.argv[2]||'http://127.0.0.1:8877')+'/');await page.getByRole('button',{name:'任务记录',exact:true}).click();await page.locator('.task-row').filter({hasText:'85c05a09'}).click();
 await page.getByRole('button',{name:'查看报告与缺失项',exact:true}).click();await page.getByText('第二部分：风险选题依据与前瞻窗口',{exact:true}).click();
 await page.getByText('查看比较过的 5 类候选',{exact:true}).click();await page.getByText('本地季节风险资料',{exact:true}).first().waitFor();await page.getByText('历史同期案例参考',{exact:true}).waitFor();
 await page.screenshot({path:'data/mixed-risk-evidence-ui.png'});
 await page.getByRole('button',{name:'关闭审核窗口',exact:true}).click();
 await page.evaluate(()=>{
  const records=Object.fromEntries(['a','b','c'].map(id=>[id,{id,title:'同一投诉的候选'+id,summary:'页面模拟代表内容'+id}]));
  dataEditor={id:'page-local-multi-merge-simulation',tab:'ambiguities',frozen:false,analysis_pending:false,pendingOnly:true,records,
   groups:['a','b','c'].map(id=>({id,representative_id:id,title:records[id].title,member_ids:[id]})),themes:[{candidate_theme:'其他',member_ids:['a','b','c']}],
   mergeDecisions:{},briefPatches:{},top10:[],merge_ambiguities:[{id:'ab',source_id:'a',target_id:'b',source_evidence:[records.a],target_evidence:[records.b],reason:'页面模拟关系一'},{id:'bc',source_id:'b',target_id:'c',source_evidence:[records.b],target_evidence:[records.c],reason:'页面模拟关系二'}]};
  openDialog('多组连续合并模拟验证');
  renderData=()=>{document.querySelector('#dialogBody').replaceChildren();renderAmbiguities(document.querySelector('#dialogBody'),dataEditor)};
  refreshReviewAnalysis=async()=>{};renderData();
 });
 await page.locator('[data-case-id="ab"]').getByRole('button',{name:'判为同一事件',exact:true}).click();
 await page.getByText('事件组甲当前包含 2 条记录；以下为代表内容。',{exact:true}).waitFor();
 await page.screenshot({path:'data/multi-group-merge-ui.png'});
 await page.locator('[data-case-id="bc"]').getByRole('button',{name:'判为同一事件',exact:true}).click();
 const merged=await page.evaluate(()=>({groups:dataEditor.groups.length,members:dataEditor.groups[0].member_ids.length,decisions:Object.keys(dataEditor.mergeDecisions).length}));
 assert.deepEqual(merged,{groups:1,members:3,decisions:2});assert.deepEqual(errors,[]);
 console.log(JSON.stringify({five_candidates_visible:true,mixed_basis_labels_visible:true,natural_prose_present:true,human_pairwise_can_merge_three_groups:merged,page_errors:errors}));
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
