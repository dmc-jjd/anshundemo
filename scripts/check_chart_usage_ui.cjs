const {chromium}=require('../data/ui-check/node_modules/playwright-core');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Users/57676/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1432,height:964}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const base='http://127.0.0.1:8879',id='5108c8a9871a4ae5a97aab6dacd915ff';
  const initial=await (await page.request.get(base+`/api/tasks/${id}/draft-view`)).json();
  const reset=await page.request.post(base+`/api/tasks/${id}/chart-settings`,{data:{expected_hash:initial.draft.content_hash,styles:{sentiment:'pie',platform:'pie',theme:'bar'}}});assert.equal(reset.status(),200);
  async function saveCharts(){const response=page.waitForResponse(r=>r.url().endsWith(`/api/tasks/${id}/chart-settings`)&&r.request().method()==='POST');await page.getByRole('button',{name:'只更新图表，保留报告文字',exact:true}).click();const result=await response;assert.equal(result.status(),200,await result.text());await page.waitForTimeout(500);await page.getByLabel('事件分类图表样式').waitFor()}
  await page.goto(base+'/');await page.getByRole('button',{name:'任务记录',exact:true}).click();
  await page.locator('.task-row').filter({hasText:id.slice(0,8)}).click();await page.getByText('Token 用量与费用估算',{exact:true}).waitFor();
  await page.screenshot({path:'data/chart-usage-monitor.png'});
  const before=await (await page.request.get(base+`/api/tasks/${id}/draft-view`)).json();
  await page.getByRole('button',{name:'查看报告与缺失项',exact:true}).click();
  await page.getByLabel('舆情调性分布图表样式').waitFor();
  assert.equal(await page.locator('.chart-setting-card').count(),5);
  assert.equal(await page.getByLabel('舆情调性分布图表样式').inputValue(),'pie');
  assert.equal(await page.getByLabel('传播平台分布图表样式').inputValue(),'pie');
  assert.equal(await page.getByLabel('事件分类图表样式').inputValue(),'bar');
  await page.getByLabel('事件分类图表样式').selectOption('barh');
  await saveCharts();
  const after=await (await page.request.get(base+`/api/tasks/${id}/draft-view`)).json();
  assert.equal(after.draft.fact_ref,before.draft.fact_ref);assert.deepEqual(after.draft.slot_values,before.draft.slot_values);
  const chart=await (await page.request.get(base+`/api/artifacts/${after.draft.chart_refs.theme}`)).json();assert.equal(chart.style,'barh');
  await page.getByLabel('事件分类图表样式').selectOption('bar');await saveCharts();
  await page.screenshot({path:'data/chart-styles-report-ui.png'});
  await page.getByRole('button',{name:'关闭审核窗口',exact:true}).click();
  // Locate the actual template task from its saved confirmed reference.
  const tasks=await (await page.request.get(base+'/api/tasks')).json();const template=tasks.find(t=>t.kind==='template'&&t.metadata.confirmed_template_ref===before.draft.template_ref);
  assert.ok(template);await page.evaluate(id=>openTemplate(id),template.id);
  assert.equal(await page.locator('.chart-setting-card').count(),5);await page.getByLabel('事件分类图表样式').selectOption('pie');
  await page.getByRole('button',{name:'另存图表样式版本',exact:true}).click();await page.waitForTimeout(900);
  await page.screenshot({path:'data/chart-styles-template-ui.png'});
  const afterTemplate=await (await page.request.get(base+'/api/tasks/'+template.id)).json();assert.notEqual(afterTemplate.metadata.confirmed_template_ref,before.draft.template_ref);
  const still=await (await page.request.get(base+`/api/tasks/${id}`)).json();assert.equal(still.template_ref,before.draft.template_ref);
  await page.getByRole('button',{name:'关闭审核窗口',exact:true}).click();
  await page.getByRole('button',{name:'设置估算单价',exact:true}).click();await page.getByLabel('估算计价时段').selectOption('off_peak');
  await page.getByRole('button',{name:'保存估算设置',exact:true}).click();await page.waitForTimeout(600);
  assert.deepEqual(errors,[]);console.log(JSON.stringify({usage_visible:true,report_styles_editable:true,template_styles_versioned:true,original_report_template_unchanged:true,manual_text_preserved:true,facts_preserved:true,pricing_editable:true,page_errors:errors}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
