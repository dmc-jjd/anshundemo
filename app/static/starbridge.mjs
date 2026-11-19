import { HANDOFF_KEY } from './starbridge-handoff.mjs?v=starbridge-20261119-4';
import { CLIENTS, buildClientDraft } from './starbridge-clients.mjs?v=starbridge-20261119-3';

const platforms = { weibo: '微博热榜', douyin: '抖音热榜', toutiao: '头条热榜', baidu: '百度热榜' };
const entry = document.getElementById('starbridgeOpen');
const dialog = document.createElement('dialog');
dialog.className = 'starbridge-dialog';
dialog.setAttribute('aria-labelledby', 'starbridgeTitle');
// 此处仅为固定壳；外部标题和摘要始终通过 textContent 写入。
dialog.innerHTML = `<form method="dialog"><header><h2 id="starbridgeTitle">星桥 · 选择约稿话题</h2><button class="btn ghost sm" value="cancel" aria-label="关闭选题窗口">关闭</button></header>
<div id="starbridgeClients" class="starbridge-clients" role="group" aria-label="选择约稿客户"></div>
<p id="starbridgeStatus" role="status" aria-live="polite" hidden></p><div id="starbridgeTopics"></div>
<footer><button class="btn ghost" value="cancel">取消</button><button class="btn primary" id="starbridgeConfirm" type="button" disabled>确认并前往 KN·AiStudio</button></footer></form>`;
document.body.appendChild(dialog);
const status = dialog.querySelector('#starbridgeStatus');
const host = dialog.querySelector('#starbridgeTopics');
const confirm = dialog.querySelector('#starbridgeConfirm');
let selected = null;
let selectedClient = null;
function setStatus(message = '') {
  status.textContent = message;
  status.hidden = !message;
}
function updateConfirm() {
  confirm.disabled = loading || !selected || !selectedClient;
}
const clientHost = dialog.querySelector('#starbridgeClients');
for (const client of CLIENTS) {
  const button = document.createElement('button');
  button.type = 'button'; button.className = 'btn ghost';
  button.dataset.client = client.id; button.textContent = client.name;
  button.setAttribute('aria-pressed', 'false');
  button.addEventListener('click', () => {
    if (loading) return;
    selectedClient = client.id;
    confirm.textContent = '确认并前往 KN·AiStudio';
    for (const item of clientHost.children) item.setAttribute('aria-pressed', String(item === button));
    setStatus(); updateConfirm();
  });
  clientHost.appendChild(button);
}
let loading = false;

async function json(url) {
  const response = await fetch(url, { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(12000) });
  if (!response.ok) throw new Error('列表读取失败');
  return response.json();
}

entry.addEventListener('click', async () => {
  selected = null;
  selectedClient = null;
  for (const item of clientHost.children) item.setAttribute('aria-pressed', 'false');
  confirm.textContent = '确认并前往 KN·AiStudio';
  confirm.disabled = true;
  host.textContent = '';
  setStatus();
  host.textContent = '正在加载…';
  dialog.showModal();
  entry.disabled = true;
  const sources = [{ name: '今日热点', url: '/api/hotspot' }, ...Object.entries(platforms).map(([id, name]) => ({ name, url: '/api/social-hotlist?platform=' + id }))];
  const results = await Promise.allSettled(sources.map(source => json(source.url)));
  host.textContent = '';
  sources.forEach((source, index) => {
    const result = results[index];
    const rows = result.status === 'fulfilled' && Array.isArray(result.value.items) ? result.value.items.filter(row => typeof row.title === 'string' && row.title.trim()) : [];
    const fallback = rows.length === 0;
    const topics = fallback ? [{ title: source.name === '今日热点' ? '数字技术如何助力公共服务提质增效' : '城市公共服务便利化引发讨论', summary: '演示选题，非实时热榜。' }] : rows;
    const group = document.createElement('fieldset');
    const legend = document.createElement('legend');
    legend.textContent = source.name;
    group.appendChild(legend);
    topics.forEach(topic => {
      const label = document.createElement('label');
      label.className = 'starbridge-topic';
      const radio = document.createElement('input');
      radio.type = 'radio'; radio.name = 'starbridge-topic';
      const copy = document.createElement('span');
      const title = document.createElement('strong'); title.textContent = topic.title;
      copy.append(title); label.append(radio, copy); group.appendChild(label);
      radio.addEventListener('change', () => { selected = { title: topic.title, source: source.name }; confirm.textContent = '确认并前往 KN·AiStudio'; setStatus(); updateConfirm(); });
    });
    host.appendChild(group);
  });
  setStatus();
  entry.disabled = false;
});

dialog.addEventListener('close', () => entry.focus());
dialog.addEventListener('cancel', event => { if (loading) event.preventDefault(); });
confirm.addEventListener('click', async () => {
  if (!selected || !selectedClient || loading) return;
  loading = true;
  updateConfirm();
  for (const button of dialog.querySelectorAll('button:not(#starbridgeConfirm)')) button.disabled = true;
  for (const field of host.querySelectorAll('fieldset')) field.disabled = true;
  confirm.textContent = '正在准备约稿材料…';
  setStatus();
  try {
    const client = CLIENTS.find(item => item.id === selectedClient);
    const url = new URL('/api/starbridge/demo-package', location.origin);
    url.searchParams.set('title', selected.title);
    url.searchParams.set('source', selected.source);
    const [pack, response, clientResponse] = await Promise.all([
      json(url.href),
      fetch('/static/starbridge-prompt.md', { signal: AbortSignal.timeout(12000), cache: 'no-cache' }),
      fetch(client.promptUrl, { signal: AbortSignal.timeout(12000), cache: 'no-cache' }),
    ]);
    if (!response.ok || !clientResponse.ok) throw new Error('客户约稿提示词读取失败');
    const text = buildClientDraft(selectedClient, selected, url.href, pack, await response.text(), await clientResponse.text());
    if (!dialog.open) return;
    sessionStorage.setItem(HANDOFF_KEY, JSON.stringify({ version: 1, text }));
    location.assign('/static/chat.html?from=starbridge&v=20261119-4');
  } catch (error) {
    setStatus('准备失败：' + error.message + '。请重试；浏览器需允许本站会话存储。');
    confirm.textContent = '重试前往 KN·AiStudio';
  } finally {
    loading = false;
    for (const button of dialog.querySelectorAll('button:not(#starbridgeConfirm)')) button.disabled = false;
    for (const field of host.querySelectorAll('fieldset')) field.disabled = false;
    updateConfirm();
  }
});
