// Read-only view check of both reviewer overview columns.
const {chromium}=require('../data/ui-check/node_modules/playwright-core');
const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Users/57676/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe',headless:true});try{
 const page=await browser.newPage({viewport:{width:1432,height:964}}),errors=[],base=process.argv[2]||'http://127.0.0.1:8765',tid=process.argv[3]||'fd74945d3561454ca33f06881ef5818c';page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/?task='+tid);await page.getByRole('button',{name:'双审核与人工终审',exact:true}).click();await page.locator('.review-summary-list').first().waitFor();
 const result={};for(const role of ['format_reviewer','content_reviewer']){const list=page.locator(`[data-reviewer="${role}"] .review-summary-list`),count=await list.locator('li').count();assert.ok(count>=1);assert.equal(await list.evaluate(el=>getComputedStyle(el).listStyleType),'decimal');result[role]=count}
 // Punctuation in a quoted title must not split that title into different items.
 assert.equal(await page.evaluate(()=>reviewSummaryItems('核对“甲；乙。丙”；另外核查。').length),2);
 await page.locator('.review-summary').scrollIntoViewIfNeeded();await page.screenshot({path:'data/reviewer-summary-numbered-ui.png'});assert.deepEqual(errors,[]);
 console.log(JSON.stringify({task:tid,numbered_summary_items:result,page_errors:errors,production_mutations:0}));
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
