// 临时验证页逻辑：POST /api/chat/stream，逐事件渲染计时器 / 分析提示 / 思考 / 搜索 / 回答 / 用量。
const API = '/api/chat/stream';
const TICK_MS = 1000; // 计时器刷新间隔
const TYPE_MS = 32;   // 「正在分析请求」打字机速度（25~40ms/字）
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

function createTurn(question) {
  const turn = el('div', 'turn');
  box.appendChild(turn);
  // 固定容器顺序：状态区 → 思考块 → 搜索行 → 回答。顺序与事件到达次序无关。
  const status = el('div', 'status');
  const timer = el('div', 'timer', '深度求索中 0s…');
  const analyzing = el('div', 'analyzing');
  status.append(timer, analyzing);
  const thinkSlot = el('div', 'think-slot');
  const searchSlot = el('div', 'search-slot');
  const answer = el('div', 'bubble answer');
  turn.append(status, thinkSlot, searchSlot, answer);

  // 计时器：点击发送即起算，每秒刷新，首个 delta 到达时停止并隐藏。
  const started = Date.now();
  const timerId = setInterval(() => {
    timer.textContent = `深度求索中 ${Math.round((Date.now() - started) / 1000)}s…`;
  }, TICK_MS);

  // 正在分析请求：把用户问题逐字打出来；思考块到达后收起。
  const phrase = `正在分析请求：${question}`;
  let typed = 0;
  const typeId = setInterval(() => {
    typed += 1;
    analyzing.textContent = phrase.slice(0, typed);
    if (typed >= phrase.length) clearInterval(typeId);
  }, TYPE_MS);

  let thought = 0;
  let details = null;
  let answerOpen = false;
  const searches = new Map();

  function stopStatus() {
    clearInterval(timerId);
    clearInterval(typeId);
    status.hidden = true;
  }

  function collapse() {
    if (details) details.open = false;
  }

  function addThought(text) {
    clearInterval(typeId);
    analyzing.hidden = true;
    if (!details) {
      details = el('details', 'think');
      details.open = true;
      details.sum = el('summary', '', '思考过程（0 字）');
      details.body = el('div', 'think-text');
      details.append(details.sum, details.body);
      thinkSlot.appendChild(details);
    }
    thought += text.length;
    details.sum.textContent = `思考过程（${thought} 字）`;
    details.body.textContent += text;
    scroll();
  }

  function searchLine(query) {
    const line = el('div', 'searchline', `正在搜索：${query}`);
    searchSlot.appendChild(line);
    searches.set(query, line);
    scroll();
    return line;
  }

  function searchDone(query, hits, readable) {
    const line = searches.get(query);
    if (line) line.textContent = `搜索「${query}」：命中 ${hits} 条，可读 ${readable} 篇`;
  }

  function searchFailed(query, reason) {
    let line = searches.get(query);
    if (!line) {
      line = el('div', 'searchline');
      searchSlot.appendChild(line);
      searches.set(query, line);
    }
    line.classList.add('failed');
    line.textContent = `搜索失败：${reason}`;
  }

  function write(text) {
    if (!answerOpen) {
      answerOpen = true;
      stopStatus();
      collapse();
    }
    answer.textContent += text;
    scroll();
  }

  function reset() {
    answer.textContent = '';
  }

  return {
    turn,
    addThought,
    collapse,
    searchLine,
    searchDone,
    searchFailed,
    write,
    reset,
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
      stopStatus();
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
    case 'answer_reset': turn.reset(); break; // 服务端判定工具语法泄漏，作废本轮正文
    case 'delta': turn.write(event.text); break;
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
  const turn = createTurn(text);
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
        if (event.type === 'answer_reset') answer = '';
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
