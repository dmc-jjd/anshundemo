const {chromium}=require('../data/ui-check/node_modules/playwright-core');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Users/57676/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1432,height:964}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8878/');
  const id='5108c8a9871a4ae5a97aab6dacd915ff';
  const before=await page.request.get(`http://127.0.0.1:8878/api/tasks/${id}`);const facts=(await before.json()).fact_ref;
  await page.evaluate(id=>openDraft(id),id);
  await page.getByLabel('报告期号',{exact:true}).waitFor();
  assert.equal(await page.locator('#dialogBody img').count(),5);
  assert.equal(await page.getByRole('button',{name:'确认报告并终审',exact:true}).count(),0);
  await page.screenshot({path:'data/writing-verification-20261108-012116/writing-ui-before.png'});
  await page.getByLabel('报告期号',{exact:true}).fill('10');await page.getByLabel('报告成文日期',{exact:true}).fill('2026-11-08');
  await page.getByRole('button',{name:'保存报告参数',exact:true}).click();
  await page.getByRole('button',{name:'确认报告并终审',exact:true}).waitFor();
  const after=await (await page.request.get(`http://127.0.0.1:8878/api/tasks/${id}`)).json();assert.equal(after.fact_ref,facts);
  await page.screenshot({path:'data/writing-verification-20261108-012116/writing-ui-parameters-saved.png'});
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({parameter_entry:true,charts:5,local_parameter_save:true,approval_enabled_only_when_complete:true,not_approved:true,fact_unchanged:true,console_errors:errors}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
