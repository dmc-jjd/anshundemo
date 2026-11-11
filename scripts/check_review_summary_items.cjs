// Pure display regression: sentence boundaries respect quotations/parentheses.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('app/static/writing-review.js','utf8'),start=source.indexOf('function reviewSummaryItems'),end=source.indexOf('const detailBeforeWritingReview',start),context={};
vm.createContext(context);vm.runInContext(source.slice(start,end),context);
const split=text=>JSON.parse(JSON.stringify(context.reviewSummaryItems(text)));
assert.deepEqual(split('第一条意见；第二条意见。第三条意见。'),['第一条意见；','第二条意见。','第三条意见。']);
assert.deepEqual(split('引用“甲；乙。丙”仍作参考；另行核查。'),['引用“甲；乙。丙”仍作参考；','另行核查。']);
assert.deepEqual(split('范围（甲；乙）已确认。\n其他意见。'),['范围（甲；乙）已确认。','其他意见。']);
assert.deepEqual(split('一段完整意见'),['一段完整意见']);console.log('4 summary display checks passed');
