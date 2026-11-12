/* 「预览并确认模板」的手动定义交互：鼠标选中一段文字 → 选择题 → 占位符 + 字段 JSON。
 *
 * 依赖（都在 app.js 里，普通脚本的全局声明）：node / button / busy / toast / api / renderDocument。
 * 后端：GET/POST /api/templates/{id}/draft*（见 app/template_draft.py）。
 * 选区坐标口径：块的标准文本——字段占位符的文本形态是 {{字段id}}，与后端 block_text() 一致。
 */
(() => {
  'use strict';

  const CODE_TEXT = {
    selection_required: '请先用鼠标选中一段文字。',
    selection_not_found: '这段文字在模板正文里定位不到（可能跨越了已有占位符），请重新选择。',
    selection_too_long: '一次最多选中 500 个字符。',
    selection_crosses_field: '选区边缘切到了已有占位符，请把选区对齐到整段纯文字。',
    unknown_choice: '该选项未被识别，请刷新页面重试。',
    unknown_block: '该段落已不在模板中，请刷新重开预览。',
    block_not_editable: '这一段尚未完成结构核对，暂不能手动定义。',
    block_requires_alignment_review: '这一段尚未完成结构核对，暂不能手动定义。',
    choice_requires_table_block: '「表格」只能用在表格块上。',
    choice_requires_paragraph_block: '这个选项只能用在普通段落上。',
    stale_template_revision: '模板已更新，正在重新载入预览…',
    immutable_confirmed_template: '该模板已确认，不能再改。',
    structured_template_missing: '模板候选尚未生成，先完成模型语义研判。',
    draft_empty: '还没有可撤销的定义。',
    not_template_task: '这不是模板任务。'
  };

  const S = {
    taskId: null, container: null, onField: null, onRevision: null,
    revision: 0, choices: [], definition: null, draft: null,
    card: null, busy: false, ready: false, highlight: null
  };

  /* ---------------------------------------------------------------- 样式 */
  const CSS = `
.td-bar{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;padding:.55rem .75rem;margin:0 0 .75rem;
  border:1px solid #d8dee9;border-radius:.5rem;background:#f7f9fc;font-size:.86rem;position:sticky;top:0;z-index:5}
.td-bar b{font-weight:600}
.td-bar .td-count{color:#1f2937}
.td-bar .td-warn{color:#b45309}
.td-bar button{font-size:.82rem;padding:.2rem .55rem}
.td-bar .td-spacer{flex:1}
.td-card{position:fixed;z-index:9999;width:22rem;max-width:calc(100vw - 2rem);background:#fff;
  border:1px solid #c7d2e0;border-radius:.6rem;box-shadow:0 12px 32px rgba(15,23,42,.18);font-size:.86rem}
.td-card header{display:flex;align-items:center;justify-content:space-between;gap:.5rem;
  padding:.5rem .7rem;border-bottom:1px solid #e6ebf3;font-weight:600}
.td-card header button{border:0;background:transparent;font-size:1rem;line-height:1;cursor:pointer;color:#64748b}
.td-quote{margin:.5rem .7rem 0;padding:.35rem .5rem;border-left:3px solid #2563eb;background:#f5f8ff;
  color:#1e3a8a;font-family:inherit;white-space:pre-wrap;max-height:4.5rem;overflow:auto}
.td-groups{padding:.4rem .7rem .2rem;max-height:17rem;overflow:auto}
.td-group{margin:.35rem 0 .55rem}
.td-group h4{margin:0 0 .3rem;font-size:.76rem;font-weight:600;color:#64748b;letter-spacing:.03em}
.td-opt{display:block;width:100%;text-align:left;margin:.18rem 0;padding:.35rem .5rem;border:1px solid #dbe3ef;
  border-radius:.4rem;background:#fff;cursor:pointer}
.td-opt:hover:not(:disabled){border-color:#2563eb;background:#f5f8ff}
.td-opt:disabled{opacity:.45;cursor:not-allowed}
.td-opt b{display:block;font-weight:600}
.td-opt small{display:block;color:#64748b;margin-top:.1rem;line-height:1.35}
.td-foot{padding:.35rem .7rem .6rem;color:#64748b;border-top:1px solid #eef2f7}
.td-json{margin:.6rem 0 0;padding:.6rem .75rem;max-height:22rem;overflow:auto;background:#0f172a;color:#e2e8f0;
  border-radius:.5rem;font-size:.76rem;line-height:1.45;white-space:pre}
.td-chip-new{outline:2px solid #2563eb;outline-offset:1px;border-radius:.25rem}
`;

  function ensureStyle() {
    if (document.getElementById('td-style')) return;
    const style = document.createElement('style');
    style.id = 'td-style';
    style.textContent = CSS;
    document.head.append(style);
  }

  /* ---------------------------------------------------------------- 文本口径 */
  function canonText(block) {
    if (!block || block.kind !== 'paragraph' || block.unmatched) return null;
    return block.parts.map(p => ('text' in p ? p.text : '{{' + p.field + '}}')).join('');
  }

  function blockByIndex(index) {
    return (S.definition?.blocks || []).find(b => String(b.index) === String(index)) || null;
  }

  // 选区起点在块标准文本里的偏移：文本节点按长度累加，占位符芯片按其 {{字段id}} 长度累加。
  function canonOffset(root, node, offset) {
    let pos = 0, found = null;
    const markerLen = el => ('{{' + (el.dataset.field || '') + '}}').length;
    const textLen = el => {
      if (el.nodeType === 3) return el.length;
      if (el.nodeType !== 1) return 0;
      if (el.classList && el.classList.contains('field-chip')) return markerLen(el);
      let total = 0;
      for (const child of el.childNodes) total += textLen(child);
      return total;
    };
    const walk = el => {
      if (found !== null) return;
      if (el.nodeType === 3) {
        if (el === node) found = pos + offset;
        else pos += el.length;
        return;
      }
      if (el.nodeType !== 1) return;
      if (el.classList && el.classList.contains('field-chip')) {
        if (el === node) found = pos;
        else pos += markerLen(el);
        return;
      }
      if (el === node) {
        // 选区锚在元素上时，它的 offset 是子节点序号。
        let inner = 0;
        for (let i = 0; i < offset && i < el.childNodes.length; i += 1) inner += textLen(el.childNodes[i]);
        found = pos + inner;
        return;
      }
      for (const child of el.childNodes) walk(child);
    };
    walk(root);
    return found;
  }

  /* ---------------------------------------------------------------- 画布 */
  function renderPaper() {
    if (!S.container) return;
    S.container.replaceChildren();
    S.container.append(buildBar());
    renderDocument(S.definition, S.container, null, S.onField);
    if (S.highlight) {
      const chip = S.container.querySelector(`.field-chip[data-field="${S.highlight}"]`);
      if (chip) chip.classList.add('td-chip-new');
      S.highlight = null;
    }
  }

  function buildBar() {
    const draft = S.draft;
    const bar = node('div', null, { class: 'td-bar' });
    const total = (S.definition?.fields || []).length;
    bar.append(node('b', '手动定义：选中正文里的文字，再回答一道选择题。'));
    bar.append(node('span', `已定义 ${draft ? draft.selection_log.length : 0} 处 · 模板字段 ${total} 个`, { class: 'td-count' }));
    if (draft?.pending?.needs_binding?.length) {
      bar.append(node('span', `· ${draft.pending.needs_binding.length} 个字段待配数据来源`, { class: 'td-warn' }));
    }
    bar.append(node('span', null, { class: 'td-spacer' }));
    const undo = node('button', '撤销上一步', { type: 'button' });
    undo.disabled = !draft?.selection_log?.length;
    undo.onclick = () => busy(undo, undoOne);
    const showJson = node('button', '查看给模型的 JSON', { type: 'button' });
    showJson.onclick = () => toggleJson();
    bar.append(undo, showJson);
    return bar;
  }

  function toggleJson() {
    const existing = S.container.querySelector('.td-json');
    if (existing) { existing.remove(); return; }
    if (!S.draft) { toast('还没有手动定义，先选中一段文字试一次。'); return; }
    const payload = {
      fields: S.draft.fields,
      output_schema: S.draft.output_schema,
      selection_log: S.draft.selection_log,
      pending: S.draft.pending
    };
    S.container.append(node('pre', JSON.stringify(payload, null, 2), { class: 'td-json' }));
  }

  /* ---------------------------------------------------------------- 选择卡 */
  function hideCard() {
    S.card?.remove();
    S.card = null;
  }

  function openCard(event) {
    hideCard();
    const selection = window.getSelection();
    const paper = S.container.querySelector('.report-paper');
    if (!paper) return;
    const anchorEl = selection?.anchorNode
      ? (selection.anchorNode.nodeType === 1 ? selection.anchorNode : selection.anchorNode.parentElement)
      : (event?.target || null);
    const blockEl = anchorEl?.closest?.('[data-block]');
    if (!blockEl || !paper.contains(blockEl)) return;
    const block = blockByIndex(blockEl.dataset.block);
    if (!block) return;

    const selected = selection && !selection.isCollapsed ? selection.toString() : '';
    // 提交给后端的是「标准文本切片」（占位符芯片折算成 {{字段id}}），它才是块的真实坐标；
    // 界面上展示的仍是用户看到的文字。
    const canonical = canonText(block) || '';
    let start = 0, end = 0, payloadText = selected;
    if (selected && selection.rangeCount) {
      const range = selection.getRangeAt(0);
      const from = canonOffset(blockEl, range.startContainer, range.startOffset);
      const to = canonOffset(blockEl, range.endContainer, range.endOffset);
      if (from !== null && to !== null && to > from) {
        start = from;
        end = to;
        const slice = canonical.slice(from, to);
        if (slice) payloadText = slice;
      }
    }
    // 整块类选项（表格/整段/图表位）不需要选区：点一下表格也能出卡片。
    if (!payloadText && !blockEl.closest('table')) return;

    let rect;
    if (selected && selection.rangeCount) rect = selection.getRangeAt(0).getBoundingClientRect();
    else rect = blockEl.getBoundingClientRect();

    S.card = buildCard({ block, selected, payloadText, start });
    document.body.append(S.card);
    const width = S.card.offsetWidth || 352;
    const height = S.card.offsetHeight || 320;
    const left = Math.min(Math.max(8, rect.left), Math.max(8, window.innerWidth - width - 12));
    let top = rect.bottom + 10;
    if (top + height > window.innerHeight - 12) top = Math.max(12, rect.top - height - 10);
    S.card.style.left = left + 'px';
    S.card.style.top = top + 'px';
  }

  function buildCard({ block, selected, payloadText, start }) {
    const card = node('div', null, { class: 'td-card', role: 'dialog', 'aria-label': '这段内容属于哪一类' });
    const head = node('header');
    head.append(node('span', '这段内容属于哪一类？'));
    const close = node('button', '×', { type: 'button', 'aria-label': '关闭选择卡' });
    close.onclick = hideCard;
    head.append(close);
    card.append(head);
    card.append(node('div', selected || '（整块）', { class: 'td-quote' }));

    const groups = node('div', null, { class: 'td-groups' });
    const isTable = block.kind === 'table';
    const isParagraph = block.kind === 'paragraph' && !block.unmatched;
    for (const choice of S.choices) {
      let group = groups.querySelector(`[data-group="${choice.group}"]`);
      if (!group) {
        const wrap = node('div', null, { class: 'td-group', 'data-group': choice.group });
        wrap.append(node('h4', choice.group));
        const list = node('div');
        wrap.append(list);
        groups.append(wrap);
        group = list;
      }
      let enabled;
      if (choice.scope === 'block') enabled = choice.id === 'table' ? isTable : isParagraph;
      else enabled = isParagraph && !!payloadText;
      const option = node('button', null, { type: 'button', class: 'td-opt' });
      option.append(node('b', choice.label), node('small', choice.description));
      option.disabled = !enabled;
      option.onclick = () => busy(option, () => submit(block, payloadText, start, choice.id));
      group.append(option);
    }
    card.append(groups);
    card.append(node('div', '选择后立即生成占位符与字段 JSON，可以接着选下一段。', { class: 'td-foot' }));
    return card;
  }

  /* ---------------------------------------------------------------- 提交 */
  async function submit(block, text, start, choice) {
    const data = await call(`/api/templates/${S.taskId}/draft/selection`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_revision: S.revision,
        block: Number(block.index),
        selected_text: text || '',
        start: start || 0,
        choice
      })
    });
    applyState(data);
    hideCard();
    S.highlight = data.field?.id || null;
    renderPaper();
    if (data.field) {
      toast(`已生成占位符 ${data.placeholder}（${data.field.display_name}）：` +
        (data.field.owner === 'data' ? '数据型字段，需另配数据来源。' : '写作阶段由 Writer 按本期证据填写。'));
    } else {
      toast('已按固定文字处理，占位符已撤销。');
    }
  }

  async function undoOne() {
    const data = await call(`/api/templates/${S.taskId}/draft/undo`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_revision: S.revision })
    });
    applyState(data);
    renderPaper();
    toast('已撤销上一步手动定义。');
  }

  function applyState(data) {
    if (data.definition) S.definition = data.definition;
    if ('draft' in data) S.draft = data.draft;
    if (Array.isArray(data.choices) && data.choices.length) S.choices = data.choices;
    if (typeof data.revision === 'number') {
      S.revision = data.revision;
      S.onRevision?.(data.revision);
    }
  }

  // 后端错误码 → 人话；未知错误保留原 message（不吞诊断信息）。
  async function call(url, opts) {
    try {
      return await api(url, opts);
    } catch (error) {
      const message = error?.message || '';
      throw new Error(CODE_TEXT[message] || message || '操作未完成，请稍后重试。');
    }
  }

  /* ---------------------------------------------------------------- 挂载 */
  async function mount({ taskId, container, onField, onRevision } = {}) {
    if (!taskId || !container) return;
    if (S.container && S.container !== container) hideCard();
    S.taskId = taskId;
    S.container = container;
    S.onField = onField;
    S.onRevision = onRevision;
    ensureStyle();

    let data;
    try {
      data = await api(`/api/templates/${taskId}/draft`);
    } catch (error) {
      // 后端还没重启时不要让整个预览页挂掉，只是没有选区交互。
      const bar = node('div', null, { class: 'td-bar' });
      bar.append(node('span', '手动定义接口未就绪（服务需要重启以加载新路由）：' + (error?.message || '')));
      container.prepend(bar);
      return;
    }
    applyState(data);
    if (!S.choices.length) S.choices = data.choices || [];

    if (!S.container.__tdBound) {
      S.container.__tdBound = true;
      S.container.addEventListener('mouseup', event => setTimeout(() => openCard(event), 0));
      document.addEventListener('mousedown', event => {
        if (S.card && !S.card.contains(event.target)) hideCard();
      });
      document.addEventListener('keydown', event => {
        if (event.key === 'Escape') hideCard();
      });
    }
    renderPaper();
  }

  window.TemplateDraft = { mount, canonText, canonOffset, choices: () => S.choices };
})();
