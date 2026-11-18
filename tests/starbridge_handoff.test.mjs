import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { HANDOFF_KEY, applyHandoff, buildDraft } from '../app/static/starbridge-handoff.mjs';

test('starbridge navigation loads a versioned studio entry and handoff module', () => {
  const html = readFileSync(new URL('../app/static/chat.html', import.meta.url), 'utf8');
  const entry = readFileSync(new URL('../app/static/chat-page.js', import.meta.url), 'utf8');
  assert.ok(/chat-page\.js\?v=starbridge-/.test(html), 'studio entry must bypass old cached script');
  assert.ok(/starbridge-handoff\.mjs\?v=starbridge-/.test(entry), 'handoff import must be versioned');
});

function storage(text) {
  const values = new Map([[HANDOFF_KEY, JSON.stringify({ version: 1, text })]]);
  return { getItem: key => values.get(key), removeItem: key => values.delete(key) };
}
test('waits for composer, preserves unsent draft and consumes handoff exactly once', () => {
  const state = storage('星桥选题');
  assert.equal(applyHandoff({}, state), false);
  let events = 0;
  const input = { innerText: '原有草稿', dispatchEvent: () => events++, focus() {} };
  const chat = { shadowRoot: { querySelector: () => input }, submitUserMessage() { assert.fail('must never auto-send'); } };
  assert.equal(applyHandoff(chat, state), true);
  assert.equal(input.innerText, '原有草稿\n\n星桥选题');
  assert.equal(events, 1);
  assert.equal(applyHandoff(chat, state), false);
});
test('draft carries chosen title, retrievable link, fixed prompt and inline demo package', () => {
  const draft = buildDraft({title: '选择乙', source: '微博热榜'}, 'http://localhost/api/starbridge/demo-package?title=B', {demo: true, citizen_comments: ['模拟']}, '固定约稿模板');
  for (const value of ['选择乙', '微博热榜', 'http://localhost/api/', '固定约稿模板', 'citizen_comments', '模拟']) assert.ok(draft.includes(value));
});
test('invalid handoff is reported and retained', () => {
  const state = storage('');
  assert.throws(() => applyHandoff({}, state), /格式无效/);
  assert.ok(state.getItem(HANDOFF_KEY));
});
