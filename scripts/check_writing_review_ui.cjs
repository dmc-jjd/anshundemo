// Isolated browser acceptance: final human edits never re-enter the model.
const {chromium}=require('../data/ui-check/node_modules/playwright-core');
const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Users/57676/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe',headless:true});try{
 const page=await browser.newPage({viewport:{width:1432,height:964}}),errors=[],tid='d2511637eb694125a92616d2a276bd08',base='http://127.0.0.1:8877';
 page.on('pageerror',e=>errors.push(e.message));
 const usageBefore=await (await page.request.get(base+`/api/tasks/${tid}/usage`)).json();
 await page.goto(base+'/?task='+tid);
 await page.getByRole('button',{name:'双审核与人工终审',exact:true}).click();
 await page.getByRole('heading',{name:'格式审核员',exact:true}).waitFor();await page.getByRole('heading',{name:'内容审核员',exact:true}).waitFor();
 await page.locator('[data-issue-id="ui-analysis"] textarea').waitFor();
 assert.equal(await page.getByRole('button',{name:'确认报告并终审',exact:true}).count(),0);
 await page.screenshot({path:'data/writing-review-before-ui.png'});
 const editor=page.locator('details[data-field-id="b40_analysis_paragraph"]');await editor.locator('summary').click();
 const input=editor.locator('textarea'),old=await input.inputValue();await input.fill(old.replace('从十月份','据十月份'));
 await editor.getByRole('button',{name:'保存人工终稿（不调用模型）',exact:true}).click();
 await page.locator('[data-issue-id="ui-analysis"]').waitFor({state:'detached'});
 
 await page.locator('[data-issue-id="ui-format"]').getByRole('button',{name:'已核对，保留当前内容',exact:true}).click();
 await page.getByRole('button',{name:'确认报告并终审',exact:true}).waitFor();
 await page.screenshot({path:'data/writing-review-after-human-ui.png'});
 const view=await (await page.request.get(base+`/api/tasks/${tid}/draft-view`)).json();
 assert.equal(view.review_ready,true);assert.ok(view.draft.slot_values.b40_analysis_paragraph.source_refs.includes('human_edit'));
 const usageAfter=await (await page.request.get(base+`/api/tasks/${tid}/usage`)).json();assert.equal(usageBefore.requests,usageAfter.requests);
 const events=await (await page.request.get(base+`/api/tasks/${tid}/events?limit=200`)).json();assert.equal(events.filter(e=>e.type==='unexpected_model_after_human').length,0);assert.deepEqual(errors,[]);
 console.log(JSON.stringify({both_reviewers_visible:true,exact_quotes_visible:true,human_edit_saved:true,retained_issue_resolved:true,final_gate_open_only_after_resolution:true,new_model_requests:0,page_errors:errors}));
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
