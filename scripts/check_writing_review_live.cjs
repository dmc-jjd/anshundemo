// Read-only verification of the actual current task. No POST requests.
const {chromium}=require('../data/ui-check/node_modules/playwright-core');
const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Users/57676/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe',headless:true});try{
 const page=await browser.newPage({viewport:{width:1432,height:964}}),errors=[],tid='d2511637eb694125a92616d2a276bd08';page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8765/?task='+tid);await page.getByRole('button',{name:'双审核与人工终审',exact:true}).click();
 await page.getByRole('heading',{name:'格式审核员',exact:true}).waitFor();await page.getByRole('heading',{name:'内容审核员',exact:true}).waitFor();
 await page.getByText('格式审核已到重试上限，已保留格式意见并继续内容审核。遗留格式问题与内容意见在此统一作最终人工核查。',{exact:true}).waitFor();
 const count=await page.locator('.writing-finding').count();assert.ok(count>0);assert.equal(await page.getByRole('button',{name:'确认报告并终审',exact:true}).count(),0);
 await page.screenshot({path:'data/writing-review-live-limit-ui.png'});await page.locator('.writing-finding').first().scrollIntoViewIfNeeded();await page.screenshot({path:'data/writing-review-live-finding-ui.png'});
 assert.deepEqual(errors,[]);console.log(JSON.stringify({live_current_task:tid,format_limit_notice_visible:true,both_reviewers_visible:true,remaining_issues_visible:count,final_approval_closed:true,page_errors:errors}));
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
