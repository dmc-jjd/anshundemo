// 临时验证页逻辑：POST /api/chat/stream，逐事件渲染思考 / 搜索 / 回答 / 用量。
const API = '/api/chat/stream';
const history = [];
const box = document.getElementById('messages');
const form = document.getElementById('composer');
const input = document.getElementById('input');
const sendBtn = document.getElementById('send');

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function scroll() { window.scrollTo({ top: document.body.scrollHeight }); }

function createTurn() {
  const turn = el('div', 'turn');
  box.appendChild(turn);
  const think = el('details', 'think');
  think.open = true;
  const sum = el('summary', '', '思考过程（0 字）');
  const thinkText = el('div', 'think-text');
  think.append(sum, thinkText);
  const answer = el('div', 'bubble answer');
  turn.append(answer);
  let thought = 0;
  let searches = new Map();
  return {
    turn, think, sum, thinkText, answer,
    addThought(text) {
      if (!think.parentNode) turn.insertBefore(think, answer);
      thought += text.length;
      sum.textContent = `思考过程（${thought} 字）`;
      thinkText.textContent += text;
      scroll();
    },
    collapse() { think.open = false; },
    searchLine(query) {
      const line = el('div', 'searchline', `正在搜索：${query}`);
      turn.insertBefore(line, answer);
      searches.set(query, line);
      scroll();
      return line;
    },
    searchDone(query, hits, readable) {
      const line = searches.get(query);
      if (line) line.textContent = `搜索「${query}」：命中 ${hits} 条，可读 ${readable} 篇`;
    },
    searchFailed(query, reason) {
      const line = searches.get(query) || (() => {
        const node = el('div', 'searchline');
        turn.insertBefore(node, answer);
        return node;
      })();
      line.classList.add('failed');
      line.textContent = `搜索失败：${reason}`;
    },
    write(text) { answer.textContent += text; scroll(); },
    usage(data) {
      const u = data.usage || {};
      const parts = [`tokens 输入 ${u.prompt_tokens ?? 0} · 输出 ${u.completion_tokens ?? 0}`];
      if (data.thinking_tokens) parts.push(`含思考 ${data.thinking_tokens}`);
      parts.push(`搜索 ${data.searches ?? 0} 次`);
      if (data.search_cost_cny) parts.push(`搜索费用 ¥${data.search_cost_cny}`);
      turn.appendChild(el('div', 'usage', parts.join(' · ')));
      scroll();
    },
    error(message) {
      turn.appendChild(el('div', 'usage', `错误：${message}`));
      scroll();
    },
  };
}

function handle(event, turn) {
  switch (event.type) {
    case 'thinking': turn.addThought(event.text); break;
    case 'thinking_end': break;
    case 'search': turn.searchLine(event.query); break;
    case 'search_result': turn.searchDone(event.query, event.hits, event.readable); break;
    case 'search_failed': turn.searchFailed(event.query || '（未收到查询词）', event.reason); break;
    case 'delta':
      turn.collapse();
      turn.write(event.text);
      break;
    case 'done': turn.usage(event); break;
    case 'error': turn.error(event.message); break;
  }
}

async function send(text) {
  const user = el('div', 'bubble user', text);
  const holder = el('div', 'turn');
  holder.appendChild(user);
  box.appendChild(holder);
  history.push({ role: 'user', content: text });
  scroll();
  const turn = createTurn();
  let answer = '';
  sendBtn.disabled = true;
  try {
    const res = await fetch(API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: history.slice(-20) }),
    });
    if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
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
        const event = JSON.parse(line.slice(5).trim());
        if (event.type === 'delta') answer += event.text;
        handle(event, turn);
      }
    }
    if (answer) history.push({ role: 'assistant', content: answer });
  } catch (err) {
    turn.error(err.message);
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  send(text);
});

input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

input.focus();
