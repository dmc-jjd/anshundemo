import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { CLIENTS, buildClientDraft, copyDraft } from '../app/static/starbridge-clients.mjs';

test('each client resolves its own prompt and carries selected topic and demo materials', () => {
  for (const client of CLIENTS) {
    const prompt = readFileSync(new URL('../app' + client.promptUrl, import.meta.url), 'utf8');
    const draft = buildClientDraft(client.id, { title: '选题乙', source: '微博' }, 'http://localhost/package', { demo: true }, '通用约稿结构', prompt);
    for (const item of [client.name, prompt.trim(), '选题乙', 'http://localhost/package', '通用约稿结构', '"demo": true']) assert.ok(draft.includes(item));
    for (const other of CLIENTS.filter(item => item !== client)) assert.ok(!draft.includes(other.name));
  }
  assert.throws(() => buildClientDraft('unknown'), /请选择约稿客户/);
  assert.throws(() => buildClientDraft('jiangchuan', {}, '', {}, '规范', ''), /提示词为空/);
});

test('clipboard success, fallback and denied access are accurately reported', async () => {
  let copied;
  await copyDraft('客户约稿', { writeText: async text => { copied = text; } }, () => assert.fail('unexpected fallback'));
  assert.equal(copied, '客户约稿');
  await copyDraft('重试', { writeText: async () => { throw new Error('denied'); } }, text => { copied = text; return true; });
  assert.equal(copied, '重试');
  await assert.rejects(copyDraft('失败', undefined, () => false), /复制失败/);
});
