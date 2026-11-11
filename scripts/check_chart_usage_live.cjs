// Read-only UI verification against the updated production demo.
const {chromium}=require('../data/ui-check/node_modules/playwright-core');
const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Users/57676/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe',headless:true});try{
 const page=await browser.newPage({viewport:{width:1432,height:964}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const base='http://127.0.0.1:8765',id='5108c8a9871a4ae5a97aab6dacd915ff';await page.goto(base+'/');
 await page.getByRole('button',{name:'任务记录',exact:true}).click();await page.locator('.task-row').filter({hasText:'5108c8a9'}).click();
 await page.getByText('Token 用量与费用估算',{exact:true}).waitFor();await page.screenshot({path:'data/chart-usage-live.png'});
 await page.getByRole('button',{name:'查看报告与缺失项',exact:true}).click();await page.getByLabel('舆情调性分布图表样式').waitFor();
 assert.equal(await page.getByLabel('舆情调性分布图表样式').inputValue(),'pie');assert.equal(await page.getByLabel('传播平台分布图表样式').inputValue(),'pie');assert.equal(await page.getByLabel('事件分类图表样式').inputValue(),'bar');
 await page.getByText(/统计口径核对：当前 1688/).waitFor();await page.screenshot({path:'data/chart-report-live.png'});
 const tasks=await (await page.request.get(base+'/api/tasks')).json();const report=tasks.find(t=>t.id===id),template=tasks.find(t=>t.metadata.confirmed_template_ref===report.template_ref);
 assert.ok(template);const source=await page.request.get(base+`/api/templates/${template.id}/charts/sentiment/source`);assert.equal(source.status(),200);
 assert.deepEqual(errors,[]);console.log(JSON.stringify({live_pies:true,live_vertical_bar:true,reference_comparison_visible:true,usage_visible:true,source_image_available:true,fact_ref:report.fact_ref,page_errors:errors}));
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
