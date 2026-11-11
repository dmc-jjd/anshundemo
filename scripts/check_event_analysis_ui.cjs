const {chromium}=require('../data/ui-check/node_modules/playwright-core');
const fs=require('fs');let browser;
(async()=>{
 browser=await chromium.launch({executablePath:'C:/Users/57676/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe',headless:true});
 const page=await browser.newPage({viewport:{width:1432,height:964}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8765/');await page.getByRole('button',{name:'任务记录',exact:true}).click();
 const id=fs.readFileSync('data/current-review-task.txt','utf8');await page.locator('.task-row').filter({hasText:id.slice(0,8)}).click();
 const task=await (await page.request.get('http://127.0.0.1:8765/api/tasks/'+id)).json();if(task.phase==='awaiting_review')await page.getByRole('button',{name:'查看并确认本期数据',exact:true}).waitFor();
 await page.screenshot({path:'data/event-analysis-stage-ui.png'});
 const ready=await page.getByRole('button',{name:'查看并确认本期数据',exact:true}).count();let top10Rows=0;
 if(ready){await page.getByRole('button',{name:'查看并确认本期数据',exact:true}).click();await page.getByLabel('本任务事件归并阈值',{exact:true}).fill('0.6');await page.getByLabel('本任务事件归并阈值',{exact:true}).fill('0.65');await page.getByRole('button',{name:'TOP10 事件梗概',exact:true}).click();top10Rows=await page.locator('.top10-table tr').count()-1;await page.screenshot({path:'data/top10-event-summaries-ui.png'});await page.getByRole('button',{name:'模型仍不确定的事件关系',exact:true}).click();await page.screenshot({path:'data/model-uncertain-events-ui.png'});await page.getByRole('button',{name:'关闭审核窗口',exact:true}).click()}
 await page.locator('.task-row').filter({hasText:'8d170eb3'}).click();await page.getByRole('button',{name:'预览并确认模板',exact:true}).click();await page.locator('#rankingRule').waitFor();
 const dimension=await page.locator('#rankingRule').inputValue();if(dimension!=='negative_warning_member_count')throw Error('incorrect template ranking dimension');
 await page.locator('.rule-settings').scrollIntoViewIfNeeded();await page.screenshot({path:'data/template-top10-rule-ui.png'});
 console.log(JSON.stringify({readyForDataReview:Boolean(ready),top10Rows,rankingDimension:dimension,pageErrors:errors,realDataConfirmed:false}));await browser.close();
})().catch(async e=>{console.error(e.message);await browser?.close();process.exitCode=1});
