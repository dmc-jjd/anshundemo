// Actual workbench, strictly read-only: no review decisions or draft edits.
const {chromium}=require('../data/ui-check/node_modules/playwright-core');
const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Users/57676/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe',headless:true});try{
 const page=await browser.newPage({viewport:{width:1432,height:964}}),errors=[],tid='d2511637eb694125a92616d2a276bd08';page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8765/?task='+tid);await page.getByRole('button',{name:'双审核与人工终审',exact:true}).click();await page.locator('.writing-finding').first().waitFor();
 const cards=page.locator('.writing-finding'),count=await cards.count();const numbers=await page.locator('.review-number').allTextContents();assert.equal(numbers.length,count);assert.ok(numbers.every(text=>/^\d+\. $/.test(text)));
 const editors=page.locator('.writing-finding textarea.review-quote');assert.ok(await editors.count()>0);assert.ok(await page.getByRole('button',{name:'保存本处修改并覆盖终稿',exact:true}).count()>0);
 await editors.first().scrollIntoViewIfNeeded();await page.screenshot({path:'data/inline-review-live-ui.png'});assert.deepEqual(errors,[]);
 console.log(JSON.stringify({live_task:tid,numbered_issues:count,inline_editors:await editors.count(),retain_button_visible:true,production_mutations:0,page_errors:errors}));
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
