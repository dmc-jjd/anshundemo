// 智能对话页（/static/chat.html）：deep-chat 组件 + 自建壳 + 我们的 SSE 后端。
// 硬约束（见 .conda/probe-deepchat/REPORT.md）：
//   1) connect.stream 必须为 true，否则只有第一帧 onResponse 会渲染；
//   2) chatStyle.fontFamily 必须在挂载前设好，否则 deep-chat 会去请求 Google Fonts；
//   3) 每帧重发整段 HTML（overwrite），折叠块 / 胶囊行 / 正文结构完全由我们控制。
import '/static/vendor/deep-chat/deepChat.bundle.js';

await customElements.whenDefined('deep-chat');

const API = '/api/chat/stream';
const STORE_KEY = 'kn-chat-sessions-v1';
const COLLAPSE_KEY = 'kn-chat-collapsed-v1';
const KN_AVATAR = 'data:image/png;base64,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';
const PLACEHOLDER = '发消息给 KN·AiStudio';

const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

// ---------------------------------------------------------------- 最小 Markdown 渲染
// 顺序是安全前提：先整段 HTML 转义（后端内容来自搜索网页，不可信），再只生成白名单标签。
// 转义后 `**` `[x](url)` `#` 等标记仍在，可以安全地逐个替换成我们自己写的标签。
function mdInline(text) {
  // text 已经过 esc()，不会再出现可执行的 < > 。
  const slots = [];
  const keep = (html) => { slots.push(html); return '\u0001' + (slots.length - 1) + '\u0001'; };
  // 1) 行内代码优先占位：代码里的星号/方括号不该被当作强调或链接。
  let s = text.replace(/`([^`\n]+)`/g, (m, code) => keep('<code>' + code + '</code>'));
  // 2) 链接：只放行 http/https；其它（javascript:、data:、相对路径）原样当普通文本。
  s = s.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, (m, label, url) => {
    const raw = url.replace(/&amp;/g, '&');
    if (!/^https?:\/\//i.test(raw)) return m;
    return keep('<a href="' + url + '" target="_blank" rel="noopener noreferrer">'
      + mdEmphasis(label) + '</a>');
  });
  // 3) 粗体 → 斜体（先粗后斜，避免 ** 被单星号规则切碎）。
  s = mdEmphasis(s);
  // 4) 还原占位（占位符用 \u0001 包裹，正常正文不会出现）。
  return s.replace(/\u0001(\d+)\u0001/g, (m, i) => slots[Number(i)]);
}

function mdEmphasis(s) {
  return s
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
}

// 表格：只认「以 | 开头的行 + 下一行是 --- 分隔行」，其余一律走段落。
// 入参是已经过 esc() 的文本，切出来的单元格同样只会进 mdInline() 的白名单标签，不会有可执行 HTML。
const MD_TABLE_SEP = /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$/;
function mdCells(line) {
  if (line.charAt(0) !== '|') return null;
  let body = line;
  if (body.endsWith('|')) body = body.slice(0, -1);
  return body.slice(1).split('|').map((cell) => cell.trim());
}
function mdTableHtml(header, rows) {
  const cell = (tag, text) => '<' + tag + '>' + mdInline(text) + '</' + tag + '>';
  return '<div class="md-table"><table><thead><tr>'
    + header.map((h) => cell('th', h)).join('')
    + '</tr></thead><tbody>'
    + rows.map((row) => '<tr>' + row.map((c) => cell('td', c)).join('') + '</tr>').join('')
    + '</tbody></table></div>';
}

function mdToHtml(src) {
  const text = esc(src).replace(/\r\n?/g, '\n');
  const out = [];
  let para = [];
  let list = null;
  let listTag = '';
  let quote = [];
  const flushPara = () => {
    if (!para.length) return;
    out.push('<p>' + para.join('<br>') + '</p>');
    para = [];
  };
  const flushList = () => {
    if (!list) return;
    out.push('<' + listTag + '>' + list.map((li) => '<li>' + li + '</li>').join('') + '</' + listTag + '>');
    list = null;
    listTag = '';
  };
  const flushQuote = () => {
    if (!quote.length) return;
    out.push('<blockquote>' + quote.join('<br>') + '</blockquote>');
    quote = [];
  };
  const flushAll = () => { flushPara(); flushList(); flushQuote(); };

  const lines = text.split('\n');
  for (let li = 0; li < lines.length; li += 1) {
    const line = lines[li].trim();
    if (!line) { flushAll(); continue; }
    // 表格要先于 hr / 标题判断：`| --- | --- |` 也是「--- 组成」，别被 hr 规则抢走。
    const cells = mdCells(line);
    if (cells && li + 1 < lines.length && MD_TABLE_SEP.test(lines[li + 1].trim())) {
      flushAll();
      const header = cells;
      const rows = [];
      let ri = li + 2;
      for (; ri < lines.length; ri += 1) {
        const rowLine = lines[ri].trim();
        if (rowLine.charAt(0) !== '|') break;
        if (MD_TABLE_SEP.test(rowLine)) continue;
        const rowCells = mdCells(rowLine) || [];
        rows.push(header.map((_, ci) => (rowCells[ci] === undefined ? '' : rowCells[ci])));
      }
      out.push(mdTableHtml(header, rows));
      li = ri - 1;
      continue;
    }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(line)) { flushAll(); out.push('<hr>'); continue; }
    const heading = line.match(/^#{1,3}\s+(.*)$/);
    if (heading) { flushAll(); out.push('<h4>' + mdInline(heading[1]) + '</h4>'); continue; }
    // 注意：整段先做了 HTML 转义，行首的 > 已变成 &gt;，这里按转义后的形态识别。
    if (line.startsWith('&gt;')) {
      flushPara(); flushList();
      quote.push(mdInline(line.replace(/^&gt;\s?/, '')));
      continue;
    }
    const ordered = line.match(/^\d+[.)]\s+(.*)$/);
    if (ordered) {
      flushPara(); flushQuote();
      if (listTag !== 'ol') { flushList(); listTag = 'ol'; list = []; }
      list.push(mdInline(ordered[1]));
      continue;
    }
    const bullet = line.match(/^[-*+]\s+(.*)$/);
    if (bullet) {
      flushPara(); flushQuote();
      if (listTag !== 'ul') { flushList(); listTag = 'ul'; list = []; }
      list.push(mdInline(bullet[1]));
      continue;
    }
    flushList(); flushQuote();
    para.push(mdInline(line));
  }
  flushAll();
  return out.join('');
}

// ---------------------------------------------------------------- storage
function loadStore() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
    if (!raw || !Array.isArray(raw.sessions)) throw new Error('empty');
    return { version: 1, activeId: raw.activeId || null, sessions: raw.sessions };
  } catch {
    return { version: 1, activeId: null, sessions: [] };
  }
}
function saveStore() {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(store)); } catch { /* quota / private mode */ }
}
const store = loadStore();

const now = () => Date.now();
const startOfDay = (ts) => { const d = new Date(ts); d.setHours(0, 0, 0, 0); return d.getTime(); };
const dayDiff = (ts) => Math.round((startOfDay(now()) - startOfDay(ts)) / 86400000);
const uid = () => 'c' + now().toString(36) + Math.random().toString(36).slice(2, 6);
const titleOf = (text) => (text || '').replace(/\s+/g, ' ').trim().slice(0, 24) || '新对话';

let activeSessionId = store.activeId;
let apiHistory = [];
let activeTurn = null;
// 当前正在跑的那条 SSE（切会话时先中止，避免旧流把帧写进新会话的界面）。
let activeStream = null;

function sessionById(id) { return store.sessions.find((s) => s.id === id) || null; }
function activeSession() { return sessionById(activeSessionId); }

function ensureSession() {
  let s = activeSession();
  if (s) return s;
  s = { id: uid(), title: '新对话', createdAt: now(), updatedAt: now(), messages: [] };
  store.sessions.unshift(s);
  store.activeId = s.id;
  activeSessionId = s.id;
  saveStore();
  renderSidebar();
  return s;
}

// ---------------------------------------------------------------- deep-chat
const AUX = `
  .outer-message-container{padding:20px 40px 6px}
  .inner-message-container{max-width:820px;margin:0 auto}
  .message-bubble{box-shadow:none;padding:11px 14px}
  .deep-chat-outer-container-role-ai .message-bubble{flex:1 1 auto;width:auto !important;
    max-width:none;margin-right:0 !important;min-width:0}
  .avatar-container{width:20px;margin-right:10px}
  .avatar-container img{width:100%;height:auto;border-radius:0;padding:0}
  .think{background:var(--field,#F5F0E8);border-radius:10px;margin:0 0 12px;overflow:hidden;
    box-sizing:border-box}
  .think > summary{display:flex;align-items:center;gap:6px;min-height:34px;padding:7px 12px;
    font-size:12.5px;line-height:1.5;letter-spacing:.01em;color:#8E8B82;cursor:pointer;
    list-style:none;user-select:none;outline:none}
  .think > summary::-webkit-details-marker{display:none}
  .think > summary::before{content:'\\25B8';font-size:10px;line-height:1;color:#8E8B82;
    transition:transform .16s ease}
  .think[open] > summary::before{content:'\\25BE'}
  .think-body{margin:0 12px 12px;padding:0 0 0 10px;border-left:2px solid rgba(155,58,44,.28);
    font-size:12.5px;line-height:1.65;letter-spacing:.01em;color:#8E8B82;
    white-space:pre-wrap;word-break:break-word}
  .search-chip{display:inline-flex;align-items:center;max-width:100%;margin:0 0 12px;padding:4px 12px;
    border-radius:100px;background:rgba(155,58,44,.10);border:1px solid rgba(155,58,44,.28);
    color:#8A3527;font-size:12.5px;line-height:1.5;letter-spacing:.01em;word-break:break-word}
  .answer{margin:0;font-size:13px;line-height:1.72;letter-spacing:.01em;color:#3D3D3A;
    white-space:normal;word-break:break-word;min-width:0}
  .answer:empty{display:none}
  .answer.error{color:#A5342A}
  /* Markdown 渲染后的排版（段落间距交给 <p> 的 margin，不再靠 pre-wrap 的空行） */
  .answer strong{font-weight:600}
  .answer em{font-style:italic}
  .answer code{background:var(--field,#F5F0E8);border-radius:3px;padding:1px 4px;font-size:12px}
  .answer a{color:var(--brand,#9B3A2C);text-decoration:underline;text-underline-offset:2px}
  .answer h4{margin:14px 0 6px;font-size:13.5px;font-weight:600;color:var(--ink)}
  .answer ol,.answer ul{margin:6px 0 10px;padding-left:20px}
  .answer li{margin:3px 0}
  .answer blockquote{margin:8px 0;padding-left:10px;border-left:2px solid var(--line);color:#8E8B82}
  .answer hr{margin:12px 0;border:0;border-top:1px solid var(--line)}
  /* Markdown 表格：外层横向滚动兜住宽表，内层 1px --line 网格 + --field 表头。
     width:max-content + min-width:100%：窄表铺满列宽，宽表按内容撑开后在容器里横向滚动，
     而不是把 8 列表格压成每列一个字。 */
  .answer .md-table{margin:8px 0 12px;overflow-x:auto;-webkit-overflow-scrolling:touch}
  .answer .md-table table{border-collapse:collapse;width:max-content;min-width:100%;font-size:13px;line-height:1.6}
  .answer .md-table th,.answer .md-table td{border:1px solid var(--line,#E6DFD8);padding:6px 10px;
    text-align:left;vertical-align:top}
  .answer .md-table th{background:var(--field,#F5F0E8);font-weight:600;color:var(--ink);white-space:nowrap}
  .answer p{margin:0 0 8px}
  .answer p:last-child{margin-bottom:0}
  .usage-line{margin-top:12px;font-size:11px;line-height:1.6;letter-spacing:.03em;color:#8E8B82}
  /* 吸底（方案 B）：宿主固定高度后，让影子 DOM 的对话网格变成「消息区 1fr + 输入框 auto」，
     消息区自己滚，输入框始终贴在对话列底部。 */
  #chat-view{height:100% !important;grid-template-rows:minmax(0,1fr) auto !important}
  #messages{min-height:0;overflow-y:auto}
  #input{width:100%;max-width:820px;margin:0 auto 34px;padding:12px 14px 8px 16px;
    background:var(--card,#FFFDFA);border:1px solid var(--line,#E6DFD8);border-radius:24px;
    min-height:64px;align-self:end;height:fit-content;align-items:center;gap:6px;
    box-sizing:border-box;transition:border-color .16s ease,box-shadow .16s ease}
  #input:focus-within{border-color:rgba(155,58,44,.30);box-shadow:0 0 0 3px rgba(155,58,44,.07)}
  #text-input-container{flex:1 1 auto;width:auto;min-width:0;min-height:28px;border:0;background:transparent;
    padding:0;margin:0;overflow:visible;box-shadow:none}
  #text-input{font-size:13.5px;line-height:1.72;color:var(--ink,#3D3D3A);padding:4px 0;
    min-height:28px;max-height:132px;outline:none}
  #text-input::before{color:#8E8B82}
  /* 发送按钮（WARNING 1）：
     ① deep-chat 把 .inside-end 绝对定位到「0×0 的 .input-button-container」上，inset-block-end 从那个
        零点往上算，所以按钮会浮到输入框外面。把该容器改成 static，定位基准回到 #input。
     ② 默认 content-box 下 32px + 7px padding ×2 会撑成 46×46，必须显式 border-box。
     ③ 文字给按钮让位：右侧预留 44px，避免长文本钻到按钮底下。 */
  #input > .input-button-container{position:static;z-index:auto}
  #input .input-button.inside-end{position:absolute;inset-inline-end:12px;inset-block-end:10px;
    width:32px;height:32px;min-width:32px;min-height:32px;padding:7px;box-sizing:border-box;
    border-radius:50%;background:rgba(155,58,44,.22);color:var(--brand,#9B3A2C);margin:0;flex:none}
  #input .input-button.inside-end[aria-disabled="false"]{background:var(--brand,#9B3A2C);color:#fff}
  #submit-icon{filter:none !important;width:18px;height:18px;display:block}
  #text-input{padding:4px 44px 4px 0}
`;

const chat = document.createElement('deep-chat');
chat.chatStyle = {
  fontFamily: 'system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif',
  width: '100%',
  height: '100%',
  backgroundColor: 'transparent',
  border: 'none',
};
chat.messageStyles = {
  default: {
    ai: {
      bubble: {
        backgroundColor: 'var(--card)',
        border: '1px solid var(--line)',
        borderRadius: '10px',
        fontSize: '13px',
        color: 'var(--ink)',
      },
    },
    user: {
      bubble: {
        backgroundColor: 'var(--brand)',
        border: 'none',
        borderRadius: '10px',
        color: '#fff',
      },
    },
  },
};
chat.avatars = {
  ai: { src: KN_AVATAR },
  user: { styles: { avatar: { display: 'none' } } },
};
chat.auxiliaryStyle = AUX;
const applyPlaceholder = () => { try { chat.setPlaceholderText(PLACEHOLDER); } catch { /* 未渲染时忽略 */ } };
applyPlaceholder();
chat.onComponentRender = applyPlaceholder;
chat.connect = { stream: true, handler: streamHandler };

// 恢复上次会话：history 必须在挂载前赋值（挂载即首渲染）。
const restored = activeSession();
if (restored && restored.messages.length) {
  chat.history = restored.messages.map(toDeepChatMessage);
  apiHistory = restored.messages
    .filter((m) => m.text)
    .map((m) => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.text }));
}
document.querySelector('#chat-slot').appendChild(chat);
setTimeout(applyPlaceholder, 200);
setTimeout(applyPlaceholder, 1200);

// ---------------------------------------------------------------- 一条 AI 消息的 HTML
function newTurn() {
  return {
    think: '',
    chips: [],
    answer: '',
    usage: '',
    error: '',
    answerStarted: false,
    userToggled: false,
    userOpen: false,
  };
}

function buildHtml(t) {
  const parts = [];
  if (t.think) {
    const open = t.userToggled ? t.userOpen : !t.answerStarted;
    parts.push('<details class="think"' + (open ? ' open' : '') + '>'
      + '<summary>思考过程（' + t.think.length + ' 字）</summary>'
      + '<div class="think-body">' + esc(t.think) + '</div>'
      + '</details>');
  }
  // 设计稿只有一行胶囊：多轮搜索时只展示最近一次，但要把总次数报给用户。
  const lastChip = t.chips.length ? t.chips[t.chips.length - 1] : null;
  if (lastChip) {
    parts.push('<div class="search-chip">' + esc(chipText(lastChip, t.chips.length)) + '</div>');
  }
  if (t.error) {
    parts.push('<div class="answer error">' + esc(t.error) + '</div>');
  } else {
    parts.push('<div class="answer">' + mdToHtml(t.answer) + '</div>');
  }
  if (t.usage) parts.push('<div class="usage-line">' + esc(t.usage) + '</div>');
  return parts.join('');
}

function chipText(chip, total) {
  let text = '搜索「' + chip.q + '」';
  if (chip.failed) text += '失败：' + chip.failed;
  else if (chip.hits != null) text += ' · 命中 ' + chip.hits + ' 条 · 可读 ' + chip.readable + ' 篇';
  else text += '…';
  if (total > 1) text += ' · 共搜 ' + total + ' 次';
  return text;
}

function usageText(ev, track) {
  const u = ev.usage || {};
  const tokens = Number(u.prompt_tokens || 0) + Number(u.completion_tokens || 0);
  const parts = [];
  // 与折叠块 summary 同一口径：都用思考正文的字符数（不再用后端的 reasoning_tokens，免得两个「字」对不上）。
  if (track && track.think.length > 0) parts.push('思考 ' + track.think.length + ' 字');
  if (typeof ev.searches === 'number') parts.push('搜索 ' + ev.searches + ' 次');
  parts.push(tokens.toLocaleString('en-US') + ' tokens');
  const cost = Number(ev.search_cost_cny || 0);
  if (cost > 0) parts.push('¥' + cost.toFixed(2));
  return parts.join(' · ');
}

function chipFor(track, ev) {
  const query = (ev && ev.query) || (track.chips.length ? track.chips[track.chips.length - 1].q : '') || '未知查询';
  let chip = track.chips.find((c) => c.q === query);
  if (!chip) {
    chip = { q: query, hits: null, readable: 0, failed: '' };
    track.chips.push(chip);
  }
  return chip;
}

function applyEvent(ev, track) {
  switch (ev.type) {
    case 'thinking':
      track.think += ev.text || '';
      break;
    case 'thinking_end':
      break;
    case 'search': {
      const chip = chipFor(track, ev);
      chip.hits = null;
      chip.failed = '';
      break;
    }
    case 'search_result': {
      const chip = chipFor(track, ev);
      chip.hits = ev.hits;
      chip.readable = ev.readable;
      chip.failed = '';
      break;
    }
    case 'search_failed': {
      const chip = chipFor(track, ev);
      chip.failed = ev.reason || '未知原因';
      break;
    }
    case 'answer_reset':
      track.answer = '';
      break;
    case 'delta':
      track.answerStarted = true;
      track.answer += ev.text || '';
      break;
    case 'done':
      track.usage = usageText(ev, track);
      break;
    case 'error':
      track.error = '出错：' + (ev.message || '未知错误');
      break;
    default:
      break;
  }
}

// 串行渲染：流式帧只保留最新一份，避免 await 堆积。alive() 为假时（用户已切走）丢弃帧。
function makeRenderer(signals, alive = () => true) {
  let pending = null;
  let loop = null;
  function pump() {
    loop = (async () => {
      while (pending !== null) {
        const html = pending;
        pending = null;
        try {
          if (alive()) await signals.onResponse({ html, overwrite: true });
        } catch { /* 渲染失败不打断 SSE */ }
      }
      loop = null;
    })();
    return loop;
  }
  return (html) => {
    pending = html;
    return loop || pump();
  };
}

function lastUserText(body) {
  const list = (body && body.messages) || [];
  for (let i = list.length - 1; i >= 0; i -= 1) {
    const item = list[i];
    if (item && item.role === 'user' && typeof item.text === 'string') return item.text;
  }
  return '';
}

function toDeepChatMessage(m) {
  return m.role === 'user'
    ? { role: 'user', text: m.text || '' }
    : { role: 'ai', html: m.html || ('<div class="answer">' + mdToHtml(m.text || '') + '</div>') };
}

// 切会话 / 新建会话前调用：中止在跑的那条流，并让它不再碰界面（catch/finally 都会检查标记）。
function stopActiveStream() {
  const current = activeStream;
  if (!current) return;
  activeStream = null;
  current.abort();
}

function streamHandler(body, signals) {
  window.__lastBody = body;
  const text = lastUserText(body);
  const session = ensureSession();
  apiHistory.push({ role: 'user', content: text });

  const isFirst = session.messages.length === 0;
  session.messages.push({ role: 'user', text, at: now() });
  if (isFirst || !session.title || session.title === '新对话') session.title = titleOf(text);
  session.updatedAt = now();
  store.activeId = session.id;
  saveStore();
  renderSidebar();
  setEmptyState();

  const track = newTurn();
  activeTurn = track;
  const render = makeRenderer(signals, () => activeTurn === track);

  const controller = new AbortController();
  let stopped = false;
  let aborted = false;                 // 被切会话中止：不写错误、不再渲染
  signals.stopClicked.listener = () => { stopped = true; controller.abort(); };
  activeStream = {
    turn: track,
    abort: () => { aborted = true; try { controller.abort(); } catch { /* noop */ } },
  };

  (async () => {
    try {
      const res = await fetch(API, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: apiHistory.slice(-20) }),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) throw new Error('HTTP ' + res.status);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let cut;
        while ((cut = buffer.indexOf('\n\n')) >= 0) {
          const block = buffer.slice(0, cut);
          buffer = buffer.slice(cut + 2);
          const line = block.split('\n').find((row) => row.startsWith('data:'));
          if (!line) continue;
          let ev;
          try { ev = JSON.parse(line.slice(5).trim()); } catch { continue; }
          applyEvent(ev, track);
          render(buildHtml(track));
        }
      }
    } catch (err) {
      if (!stopped && !aborted) {
        track.error = '连接失败：' + (err && err.message ? err.message : err);
      }
    } finally {
      // 最后一帧必须落盘（done 的用量行可能刚写入 track）；已切走则只落库不动界面。
      if (activeTurn === track) await render(buildHtml(track));
      try { signals.onClose(); } catch { /* noop */ }
      if (track.answer) apiHistory.push({ role: 'assistant', content: track.answer });
      if (track.think || track.answer || track.error || track.usage) {
        session.messages.push({
          role: 'ai',
          html: buildHtml(track),
          text: track.answer,
          at: now(),
        });
        session.updatedAt = now();
        saveStore();
        renderSidebar();
      }
      if (activeTurn === track) activeTurn = null;
      if (activeStream && activeStream.turn === track) activeStream = null;
      setEmptyState();
      window.__lastTurn = { think: track.think, answer: track.answer, usage: track.usage };
    }
  })();
}

// 用户手动展开/收起思考块：记住其意图，后续帧按意图重发 open 状态。
function watchToggles() {
  const sr = chat.shadowRoot;
  if (!sr) { setTimeout(watchToggles, 80); return; }
  sr.addEventListener('click', (event) => {
    const target = event.target;
    if (!target || !target.closest || !activeTurn) return;
    const summary = target.closest('summary');
    const details = summary && summary.closest('details');
    if (!details) return;
    // 只认当前流式这一条消息的折叠块（历史消息的折叠不影响本轮重发）。
    const outer = details.closest('.outer-message-container');
    const outers = sr.querySelectorAll('.outer-message-container');
    if (!outer || outer !== outers[outers.length - 1]) return;
    activeTurn.userToggled = true;
    activeTurn.userOpen = !details.open; // click 默认动作在派发后执行
  }, true);
}
watchToggles();

// ---------------------------------------------------------------- 左栏
const listEl = document.querySelector('#sb-list');
const railEl = document.querySelector('#rail-list');

// 事件委托：会话条目每次 renderSidebar 都会重建，绑在稳定的容器上才不会失效。
listEl.addEventListener('click', (event) => {
  const node = event.target && event.target.closest ? event.target.closest('[data-session-id]') : null;
  if (!node || !listEl.contains(node)) return;
  event.preventDefault();
  openSession(node.dataset.sessionId);
});

function bucketOf(ts) {
  const d = dayDiff(ts);
  if (d <= 0) return '今天';
  if (d === 1) return '昨天';
  if (d <= 7) return '7 天内';
  if (d <= 30) return '30 天内';
  return '更早';
}

function renderSidebar() {
  const filter = (document.querySelector('#sb-filter')?.value || '').trim().toLowerCase();
  const sessions = store.sessions
    .slice()
    .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
    .filter((s) => !filter || (s.title || '').toLowerCase().includes(filter));

  listEl.textContent = '';
  if (!sessions.length) {
    listEl.appendChild(el('div', 'none', filter ? '没有匹配的会话' : '还没有会话'));
  }
  const order = ['今天', '昨天', '7 天内', '30 天内', '更早'];
  let lastBucket = null;
  for (const s of sessions) {
    const bucket = bucketOf(s.updatedAt || s.createdAt || now());
    if (bucket !== lastBucket) {
      lastBucket = bucket;
      const head = el('div', 'grp');
      head.appendChild(el('span', '', bucket));
      if (bucket === '今天') {
        const gear = el('button', 'grp-gear');
        gear.type = 'button';
        gear.title = '会话管理';
        gear.setAttribute('aria-label', '会话管理');
        gear.innerHTML = '<svg class="ico" viewBox="0 0 24 24" fill="currentColor" fill-rule="evenodd" aria-hidden="true"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.33-.02-.64-.07-.94l2.03-1.58a.49.49 0 0 0 .12-.61l-1.92-3.32a.48.48 0 0 0-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54a.48.48 0 0 0-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96a.48.48 0 0 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58a.49.49 0 0 0-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.57 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6A3.6 3.6 0 1 1 12 8.4a3.6 3.6 0 0 1 0 7.2z"/></svg>';
        head.appendChild(gear);
      }
      listEl.appendChild(head);
    }
    const conv = el('a', 'conv', s.title || '新对话');
    conv.href = '#';
    conv.title = s.title || '新对话';
    conv.dataset.sessionId = s.id;   // 由 #sb-list 上的事件委托统一处理（重渲染不丢监听）
    if (s.id === activeSessionId) conv.setAttribute('aria-current', 'true');
    listEl.appendChild(conv);
  }

  railEl.textContent = '';
  for (const s of store.sessions.slice().sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0)).slice(0, 12)) {
    const item = el('button', 'rail-item', (s.title || '新').slice(0, 1));
    item.type = 'button';
    item.title = s.title || '新对话';
    if (s.id === activeSessionId) item.setAttribute('aria-current', 'true');
    item.addEventListener('click', () => openSession(s.id));
    railEl.appendChild(item);
  }
}

function openSession(id) {
  if (!sessionById(id)) return;
  if (id === activeSessionId) { try { window.scrollTo(0, 0); } catch { /* noop */ } }
  stopActiveStream();                      // 切会话先停旧流，避免串到新会话界面
  activeSessionId = id;
  store.activeId = id;
  saveStore();
  const s = activeSession();
  apiHistory = (s.messages || []).filter((m) => m.text)
    .map((m) => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.text }));
  try { chat.clearMessages(); } catch { /* noop */ }
  for (const m of s.messages || []) {
    try { chat.addMessage(toDeepChatMessage(m)); } catch { /* noop */ }
  }
  try { window.scrollTo(0, 0); } catch { /* noop */ }
  renderSidebar();
  setEmptyState();
}

function setEmptyState() {
  const s = activeSession();
  const has = !!(s && s.messages.length);
  document.querySelector('#chat').classList.toggle('has-thread', has);
}

function startNewChat() {
  stopActiveStream();
  const s = { id: uid(), title: '新对话', createdAt: now(), updatedAt: now(), messages: [] };
  store.sessions.unshift(s);
  store.activeId = s.id;
  activeSessionId = s.id;
  apiHistory = [];
  saveStore();
  try { chat.clearMessages(); } catch { /* noop */ }
  renderSidebar();
  setEmptyState();
  try { chat.focusInput(); } catch { /* noop */ }
}

document.querySelector('#new-chat').addEventListener('click', startNewChat);
document.querySelector('#new-chat-rail').addEventListener('click', startNewChat);

document.querySelector('#sb-search-btn').addEventListener('click', () => {
  const box = document.querySelector('#sb-search');
  box.hidden = !box.hidden;
  if (!box.hidden) document.querySelector('#sb-filter').focus();
});
document.querySelector('#sb-filter').addEventListener('input', renderSidebar);

document.querySelectorAll('[data-collapse]').forEach((btn) => {
  btn.addEventListener('click', () => {
    const collapsed = document.body.classList.toggle('is-collapsed');
    try { localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0'); } catch { /* noop */ }
  });
});
if (localStorage.getItem(COLLAPSE_KEY) === '1') document.body.classList.add('is-collapsed');

document.querySelector('#today').textContent = new Date().toLocaleDateString('zh-CN', {
  year: 'numeric', month: '2-digit', day: '2-digit',
}).replace(/\//g, '-');

renderSidebar();
setEmptyState();
