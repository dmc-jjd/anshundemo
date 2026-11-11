// Actual latest report: read-only completion and display verification.
const {chromium}=require('../data/ui-check/node_modules/playwright-core');
const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Users/57676/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe',headless:true});try{
 const page=await browser.newPage({viewport:{width:1432,height:964}}),errors=[],tid='fd74945d3561454ca33f06881ef5818c',base='http://127.0.0.1:8765';page.on('pageerror',e=>errors.push(e.message));
 const response=await page.request.get(base+`/api/tasks/${tid}/draft-view`),view=await response.json();assert.deepEqual(view.missing,[]);
 const analysis=view.draft.slot_values.b40_analysis_paragraph.value,outlook=view.draft.slot_values.monthly_recommendations.value;assert.ok(analysis.length>=300&&analysis.length<=500);assert.equal(outlook.length,3);
 await page.goto(base+'/?task='+tid);await page.getByRole('button',{name:'查看报告与缺失项',exact:true}).click();await page.locator('.report-paper').waitFor();
 const text=await page.locator('.report-paper').textContent();assert.ok(text.includes(analysis));for(const paragraph of outlook)assert.ok(text.includes(paragraph));
 assert.equal(await page.locator('.report-paper > ol > li').count(),3);await page.locator('.report-paper > ol').scrollIntoViewIfNeeded();await page.screenshot({path:'data/second-section-restored-live-ui.png'});
 assert.deepEqual(errors,[]);console.log(JSON.stringify({live_task:tid,missing_fields:0,analysis_characters:analysis.length,outlook_items:outlook.length,paragraphs_visible:true,page_errors:errors,production_mutations:0}));
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
