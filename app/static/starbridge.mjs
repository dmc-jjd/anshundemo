import { HANDOFF_KEY, buildDraft } from './starbridge-handoff.mjs?v=starbridge-20261118-2';

const platforms = { weibo: '微博热榜', douyin: '抖音热榜', toutiao: '头条热榜', baidu: '百度热榜' };
const entry = document.getElementById('starbridgeOpen');
const dialog = document.createElement('dialog');
dialog.className = 'starbridge-dialog';
dialog.setAttribute('aria-labelledby', 'starbridgeTitle');
// 此处仅为固定壳；外部标题和摘要始终通过 textContent 写入。
dialog.innerHTML = `<form method="dialog"><header><h2 id="starbridgeTitle">星桥 · 选择约稿话题</h2><button class="btn ghost sm" value="cancel" aria-label="关闭选题窗口">关闭</button></header>
<p class="starbridge-note">从今日热点与社媒热榜中单选一个话题。当前为演示流程，原文与评论数据包使用模拟材料。</p>
<p id="starbridgeStatus" role="status" aria-live="polite"></p><div id="starbridgeTopics"></div>
<footer><button class="btn ghost" value="cancel">取消</button><button class="btn primary" id="starbridgeConfirm" type="button" disabled>确认并前往 KN·AiStudio</button></footer></form>`;
document.body.appendChild(dialog);
const status = dialog.querySelector('#starbridgeStatus');
const host = dialog.querySelector('#starbridgeTopics');
const confirm = dialog.querySelector('#starbridgeConfirm');
let selected = null;
let loading = false;

async function json(url) {
  const response = await fetch(url, { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(12000) });
  if (!response.ok) throw new Error('列表读取失败');
  return response.json();
}

entry.addEventListener('click', async () => {
  selected = null;
  confirm.disabled = true;
  host.textContent = '';
  status.textContent = '正在读取热点与四个平台热榜…';
  dialog.showModal();
  entry.disabled = true;
  const sources = [{ name: '今日热点', url: '/api/hotspot' }, ...Object.entries(platforms).map(([id, name]) => ({ name, url: '/api/social-hotlist?platform=' + id }))];
  const results = await Promise.allSettled(sources.map(source => json(source.url)));
  let fallbackCount = 0;
  sources.forEach((source, index) => {
    const result = results[index];
    const rows = result.status === 'fulfilled' && Array.isArray(result.value.items) ? result.value.items.filter(row => typeof row.title === 'string' && row.title.trim()) : [];
    const fallback = rows.length === 0;
    if (fallback) fallbackCount++;
    const topics = fallback ? [{ title: source.name === '今日热点' ? '数字技术如何助力公共服务提质增效' : '城市公共服务便利化引发讨论', summary: '演示选题，非实时热榜。' }] : rows;
    const group = document.createElement('fieldset');
    const legend = document.createElement('legend');
    legend.textContent = source.name + (fallback ? ' · 演示选题' : result.value.demo ? ' · 截图模拟数据' : ' · 当前列表');
    group.appendChild(legend);
    topics.forEach(topic => {
      const label = document.createElement('label');
      label.className = 'starbridge-topic';
      const radio = document.createElement('input');
      radio.type = 'radio'; radio.name = 'starbridge-topic';
      const copy = document.createElement('span');
      const title = document.createElement('strong'); title.textContent = topic.title;
      const summary = document.createElement('small'); summary.textContent = topic.summary || '确认后携带话题及模拟原文、评论数据包进入约稿。';
      copy.append(title, summary); label.append(radio, copy); group.appendChild(label);
      radio.addEventListener('change', () => { selected = { title: topic.title, source: source.name }; confirm.disabled = false; });
    });
    host.appendChild(group);
  });
  status.textContent = fallbackCount ? `${fallbackCount} 个列表暂无可用数据，已补充演示选题；所有选题均使用模拟材料包。` : '已读取全部列表。当前材料包为模拟数据，选择一个话题继续。';
  entry.disabled = false;
});

dialog.addEventListener('close', () => entry.focus());
dialog.addEventListener('cancel', event => { if (loading) event.preventDefault(); });
confirm.addEventListener('click', async () => {
  if (!selected || loading) return;
  loading = true;
  confirm.disabled = true;
  status.textContent = '正在准备约稿材料…';
  try {
    const url = new URL('/api/starbridge/demo-package', location.origin);
    url.searchParams.set('title', selected.title);
    url.searchParams.set('source', selected.source);
    const [pack, response] = await Promise.all([json(url.href), fetch('/static/starbridge-prompt.md', { signal: AbortSignal.timeout(12000) })]);
    if (!response.ok) throw new Error('约稿提示词读取失败');
    const text = buildDraft(selected, url.href, pack, await response.text());
    if (!dialog.open) return;
    sessionStorage.setItem(HANDOFF_KEY, JSON.stringify({ version: 1, text }));
    location.assign('/static/chat.html?from=starbridge&v=20261118-2');
  } catch (error) {
    status.textContent = '准备失败：' + error.message + '。请重试；浏览器需允许本站会话存储。';
    confirm.disabled = false;
  } finally { loading = false; }
});
