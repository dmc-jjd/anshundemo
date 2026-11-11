// Isolated database UI validation. No production writes and no model calls.
const {chromium}=require('../data/ui-check/node_modules/playwright-core');
const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Users/57676/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe',headless:true});try{
 const page=await browser.newPage({viewport:{width:1432,height:964}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const base='http://127.0.0.1:8877',id='85c05a094302469a93468bec88f1dcf2';
 const before=await (await page.request.get(`${base}/api/tasks/${id}`)).json();
 const eventsBefore=await (await page.request.get(`${base}/api/tasks/${id}/events`)).json();
 await page.goto(base);await page.getByRole('button',{name:'报告处理',exact:true}).click();
 await page.locator('#reportTemplate').selectOption(before.template_ref);
 await page.waitForFunction(()=>document.querySelector('#reportIssue').value==='10');
 assert.match(await page.locator('#parameterSuggestion').innerText(),/推算/);
 await page.screenshot({path:'data/report-processing-parameters.png'});
 await page.getByRole('button',{name:'任务记录',exact:true}).click();await page.locator('.task-row').filter({hasText:'85c05a09'}).click();
 await page.getByRole('button',{name:'报告参数：期号与成文日期',exact:true}).click();
 await page.getByLabel('本期报告期号',{exact:true}).fill('10');await page.getByLabel('本期成文日期',{exact:true}).fill('2026-11-04');
 await page.getByRole('button',{name:'保存报告参数',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('#reviewDialog').open);
 const after=await (await page.request.get(`${base}/api/tasks/${id}`)).json();
 assert.equal(after.fact_ref,before.fact_ref);
 const view=await (await page.request.get(`${base}/api/tasks/${id}/draft-view`)).json();
 assert.deepEqual(view.missing,['monthly_recommendations']);
 const eventsAfter=await (await page.request.get(`${base}/api/tasks/${id}/events`)).json();
 assert.equal(eventsAfter.filter(e=>e.type.startsWith('model_')).length,eventsBefore.filter(e=>e.type.startsWith('model_')).length);
 await page.getByRole('button',{name:'查看报告与缺失项',exact:true}).click();
 await page.getByText('第二部分：历史同期选题依据与前瞻窗口',{exact:true}).click();
 await page.getByText('实际联网记录：成功搜索 11 次，阅读原文 14 次。',{exact:true}).waitFor();
 await page.screenshot({path:'data/historical-search-evidence-visible.png'});
 await page.getByRole('button',{name:'关闭审核窗口',exact:true}).click();
 // Exercise the real member renderer in a page-local simulation.
 await page.evaluate(()=>{
  const long='目标事件：某地群众反映服务问题，以下是用于查看完整标题的测试内容。'.repeat(4);
  dataEditor={id:'page-local-simulation',tab:'events',frozen:false,analysis_pending:false,records:{a:{title:'来源事件',summary:'原始梗概'},b:{title:long,summary:'目标记录原文梗概，供人工核对。',published:'2026-10-10',source:'页面模拟'}},themes:[{candidate_theme:'其他',member_ids:['a','b']}],groups:[{id:'a',title:'来源事件',representative_id:'a',member_ids:['a']},{id:'b',title:long,representative_id:'b',member_ids:['b']}]};
  openDialog('移动目标模拟检查');renderMembers(document.querySelector('#dialogBody'),dataEditor.groups[0]);
 });
 assert.equal(await page.locator('select[aria-label="移入目标事件或分类"]').count(),0);
 await page.getByRole('button',{name:'选择移入目标事件',exact:true}).click();await page.getByLabel('搜索目标事件',{exact:true}).fill('群众反映');
 await page.locator('.move-target-option').click();
 assert.match(await page.locator('.move-target-preview').innerText(),/已选择目标事件/);
 await page.getByText('查看目标事件全部记录',{exact:true}).click();
 await page.getByText('目标记录原文梗概，供人工核对。',{exact:true}).waitFor();
 await page.screenshot({path:'data/event-target-search-preview.png'});
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({automatic_issue:10,processing_date_editable:true,existing_draft_parameters_saved_without_model:true,missing_after_parameters:view.missing,search_count_visible:11,fetch_count_visible:14,long_target_search_and_full_preview:true,frozen_fact_unchanged:true,page_errors:errors}));
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
