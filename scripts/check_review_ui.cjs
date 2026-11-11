const {chromium}=require('../data/ui-check/node_modules/playwright-core');
const fs=require('fs');
let launchedBrowser;
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Users/57676/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe',headless:true});
 launchedBrowser=browser;
 const page=await browser.newPage({viewport:{width:1432,height:964}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8765/');await page.getByRole('button',{name:'任务记录',exact:true}).click();
 const id=fs.readFileSync('data/current-review-task.txt','utf8');
 await page.locator('.task-row').filter({hasText:id.slice(0,8)}).click();
 await page.getByRole('button',{name:'查看并确认本期数据',exact:true}).waitFor();
 if(!await page.getByRole('button',{name:'开始写作',exact:true}).isDisabled())throw Error('writing gate is open');
 await page.getByRole('button',{name:'查看并确认本期数据',exact:true}).click();
 await page.locator('.result-row').first().waitFor();await page.locator('.result-row').first().click();
 await page.locator('.member-card').first().waitFor();
 await page.screenshot({path:'data/data-review-ui.png'});
 const groupsBefore=Number(await page.locator('.review-stats strong').nth(2).textContent());
 const multi=page.locator('.result-row').filter({hasText:'4 条记录'}).first();
 if(await multi.count()){await multi.click();await page.locator('.member-card input[type=checkbox]').first().check();await page.getByRole('button',{name:'将勾选记录拆成新事件',exact:true}).click();const after=Number(await page.locator('.review-stats strong').nth(2).textContent());if(after!==groupsBefore+1)throw Error('split event did not update review state')}

 const eventRows=await page.locator('.result-row').count();const visibleMembers=await page.locator('.member-card').count();
 await page.getByRole('button',{name:'分类与成员',exact:true}).click();await page.locator('.result-row').first().click();
 if(!await page.getByRole('button',{name:'应用分类名称',exact:true}).isVisible())throw Error('theme editing is missing');
 await page.screenshot({path:'data/theme-review-ui.png'});
 await page.getByRole('button',{name:'关闭审核窗口',exact:true}).click();
 await page.locator('.task-row').filter({hasText:'8d170eb3'}).click();await page.getByRole('button',{name:'预览并确认模板',exact:true}).click();
 await page.locator('.field-chip').first().waitFor();await page.locator('.field-chip').first().click();
 if(!await page.locator('.historical-example').first().isVisible())throw Error('historical examples are missing');
 await page.screenshot({path:'data/template-review-ui.png'});
 const count=await page.locator('.field-chip').count();
 await page.getByRole('button',{name:'确认并保存模板',exact:true}).click();
 if(!await page.locator('#dialogNotice').textContent())throw Error('missing rule validation');
 await page.getByRole('button',{name:'关闭审核窗口',exact:true}).click();
 console.log(JSON.stringify({writingBlocked:true,eventRows,visibleMembers,templateFields:count,logRows:await page.locator('#eventList .event').count(),pageErrors:errors,realDataConfirmed:false}));
 await browser.close();
})().catch(async e=>{console.error(e.message);await launchedBrowser?.close();process.exitCode=1});
