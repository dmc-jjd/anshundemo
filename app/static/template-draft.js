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
    not_template_task: '这不是模板任务。',
    confirmed_template_required: '模板还没有确认，先确认模板再来审核。',
    advice_not_structured: '模型返回的意见不是约定的 JSON，请重试。',
    model_not_configured: '尚未配置模型接口，暂时不能审核。',
    task_paused: '任务已暂停，模型调用已停止。'
  };

  const S = {
    taskId: null, container: null, onField: null, onRevision: null,
    revision: 0, choices: [], definition: null, draft: null,
    card: null, busy: false, ready: false, highlight: null
  };

  /* ---------------------------------------------------------------- 样式 */
  // .td-* 样式已迁到 app/static/style.css：与全站设计令牌同源、随断点响应式生效。
  // 本文件不再向 <head> 注入私有样式（旧注入会以更后顺序覆盖全局主题）。

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
    // 卡片挂在顶层 <dialog> 内：dialog.showModal() 进入 top layer，body 上的 fixed 元素会被盖住。
    // 无 dialog 时退回 body（旧行为不变）。
    const host = document.getElementById('reviewDialog');
    (host && host.open ? host : document.body).append(S.card);
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

  /* ---------------------------------------------------------------- 只读审核 */
  // 确认后的第二次模型研判：只返回修改意见。页面没有「应用」「接受」按钮——
  // 意见不写回模板，要改仍走「手动定义 → 重新确认」这条人工路径。
  const A = { taskId: null, panel: null, definition: null, running: false };

  function adviceFieldLabel(fieldId) {
    const field = (A.definition?.fields || []).find(item => item.id === fieldId);
    return field ? (field.display_name || field.id) : (fieldId || '整份模板');
  }

  function renderAdvice(result) {
    if (!A.panel) return;
    A.panel.replaceChildren();
    if (!result) {
      A.panel.append(node('p', '还没有审核意见。点击上方「LLM审核」让模型再审一遍：只返回修改意见，不改模板。',
        { class: 'td-advice-empty' }));
      return;
    }
    const items = Array.isArray(result.items) ? result.items : [];
    const head = node('div', null, { class: 'td-advice-head' });
    head.append(node('strong', `模型修改意见 ${items.length} 条`));
    if (result.created_at) {
      const at = new Date(result.created_at);
      if (!Number.isNaN(at.getTime())) head.append(node('span', at.toLocaleString('zh-CN'), { class: 'td-advice-time' }));
    }
    head.append(node('span', '只读展示：不接受、不应用。', { class: 'td-advice-readonly' }));
    A.panel.append(head);
    if (!items.length) {
      A.panel.append(node('p', '模型这次没有提出修改意见。', { class: 'td-advice-empty' }));
      return;
    }
    // 只分两级：重要（红）/ 建议（灰）。模型自创的级别一律并入「建议」，不新增颜色。
    const groups = [
      { severity: '重要', cls: 'td-important', items: items.filter(item => item.severity === '重要') },
      { severity: '建议', cls: 'td-suggest', items: items.filter(item => item.severity !== '重要') }
    ];
    for (const group of groups) {
      if (!group.items.length) continue;
      const section = node('div', null, { class: 'td-advice-group ' + group.cls });
      section.append(node('h4', `${group.severity}（${group.items.length}）`));
      const list = node('ul');
      for (const item of group.items) {
        const li = node('li');
        li.append(node('span', adviceFieldLabel(item.field_id), { class: 'td-advice-field' }));
        li.append(node('p', item.message || '', { class: 'td-advice-msg' }));
        if (item.evidence) li.append(node('blockquote', '原文依据：' + item.evidence, { class: 'td-advice-evidence' }));
        list.append(li);
      }
      section.append(list);
      A.panel.append(section);
    }
  }

  async function runAdvice(trigger) {
    if (A.running) return;
    A.running = true;
    const label = trigger.textContent;
    trigger.disabled = true;
    trigger.textContent = '模型审阅中…';
    if (A.panel) {
      A.panel.replaceChildren(node('p', '模型正在按字段审阅已确认模板，通常需要 30—90 秒，请不要关闭窗口。',
        { class: 'td-advice-empty' }));
    }
    try {
      const data = await call(`/api/templates/${A.taskId}/advice`, { method: 'POST' });
      renderAdvice(data);
      toast(`模型修改意见已返回 ${(data.items || []).length} 条（只读，不改模板）。`);
    } catch (error) {
      const message = error?.message || '审核未完成。';
      if (A.panel) A.panel.replaceChildren(node('p', '审核未完成：' + message, { class: 'td-advice-error' }));
      toast('审核未完成：' + message);
    } finally {
      A.running = false;
      trigger.disabled = false;
      trigger.textContent = label;
    }
  }

  async function mountAdvice({ taskId, container }) {
    A.taskId = taskId;
    container.querySelectorAll('.td-advice-bar,.td-advice').forEach(element => element.remove());
    try {
      A.definition = (await api(`/api/templates/${taskId}/definition`)).definition;
    } catch {
      A.definition = null;
    }
    const bar = node('div', null, { class: 'td-bar td-advice-bar' });
    bar.append(node('b', '模板已确认，只读。'));
    bar.append(node('span', '可让模型再审一遍：只返回修改意见，不改模板与字段。', { class: 'td-count' }));
    const run = node('button', 'LLM审核', { type: 'button' });
    run.onclick = () => runAdvice(run);
    bar.append(node('span', null, { class: 'td-spacer' }), run);
    A.panel = node('div', null, { class: 'td-advice' });
    container.prepend(bar);
    container.append(A.panel);
    renderAdvice(null);
    try {
      const last = await api(`/api/templates/${taskId}/advice`);
      if (last && last.available) renderAdvice(last);
    } catch {
      // 读不回上次结果时保持空态，不阻塞预览。
    }
  }

  /* ---------------------------------------------------------------- 挂载 */
  async function mount({ taskId, container, onField, onRevision, confirmed } = {}) {
    if (!taskId || !container) return;
    if (confirmed) {
      // 已确认模板不可再手动定义，只提供只读审核入口。
      await mountAdvice({ taskId, container });
      return;
    }
    if (S.container && S.container !== container) hideCard();
    S.taskId = taskId;
    S.container = container;
    S.onField = onField;
    S.onRevision = onRevision;

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
