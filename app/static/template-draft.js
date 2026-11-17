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
    custom_definition_required: '请先填写自定义字段的定义。',
    custom_display_name_required: '请填写字段显示名（1~20 字）。',
    custom_display_name_too_long: '字段显示名最多 20 个字。',
    custom_semantic_required: '请用一句话说明这个字段的含义（告诉 Writer 这个字段怎么填）。',
    custom_semantic_too_long: '字段含义请控制在 200 字以内。',
    custom_owner_invalid: '请选择这个字段由谁来填。',
    custom_data_note_too_long: '数据来源说明请控制在 200 字以内。'
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
      option.onclick = () => {
        // 自定义字段不跳页：在卡片内展开小表单，填完定义再生成占位符。
        if (choice.id === 'custom_text') openCustomForm(card, block, payloadText, start);
        else busy(option, () => submit(block, payloadText, start, choice.id));
      };
      group.append(option);
    }
    card.append(groups);
    card.append(node('div', '选择后立即生成占位符与字段 JSON，可以接着选下一段。', { class: 'td-foot' }));
    return card;
  }

  /* ------------------------------------------------------ 自定义字段小表单 */
  function openCustomForm(card, block, text, start) {
    card.querySelector('.td-custom-form')?.remove();
    // 已选定「自定义」：收起类型列表与页脚，把卡片空间让给小表单（取消再恢复）。
    const groups = card.querySelector('.td-groups');
    const foot = card.querySelector('.td-foot');
    if (groups) groups.style.display = 'none';
    if (foot) foot.style.display = 'none';
    const form = node('div', null, { class: 'td-custom-form' });
    form.style.cssText =
      'padding:9px 12px 11px;border-top:1px solid var(--line-soft,#e7e1da);display:flex;flex-direction:column;gap:7px';

    const nameInput = node('input', null, {
      type: 'text', maxlength: '20', autocomplete: 'off',
      placeholder: '字段显示名（必填，1~20 字），如：整体态势措辞', 'aria-label': '字段显示名'
    });
    const semanticInput = node('textarea', null, {
      rows: '2', maxlength: '200',
      placeholder: '字段含义（必填，一句话告诉 Writer 这个字段怎么填）', 'aria-label': '字段含义'
    });

    // 谁来填：两个单选项；选「程序按数据算」时才展开可选的数据来源说明。
    const ownerLine = node('div', null, { class: 'td-custom-owner' });
    ownerLine.style.cssText = 'display:flex;gap:14px;flex-wrap:wrap';
    const ownerWriter = node('input', null, { type: 'radio', name: 'td-custom-owner', value: 'writer' });
    const ownerData = node('input', null, { type: 'radio', name: 'td-custom-owner', value: 'data' });
    ownerWriter.checked = true;
    const writerLabel = node('label');
    writerLabel.style.cssText = 'display:inline-flex;gap:5px;align-items:center;font-size:12px';
    writerLabel.append(ownerWriter, document.createTextNode('Writer 按本期证据写'));
    const dataLabel = node('label');
    dataLabel.style.cssText = 'display:inline-flex;gap:5px;align-items:center;font-size:12px';
    dataLabel.append(ownerData, document.createTextNode('程序按数据算'));
    ownerLine.append(writerLabel, dataLabel);

    const dataLine = node('div', null, { class: 'td-custom-data' });
    dataLine.style.cssText = 'display:none;flex-direction:column;gap:4px';
    const dataNote = node('input', null, {
      type: 'text', maxlength: '200', autocomplete: 'off',
      placeholder: '数据来源说明（可选，可留空），如：来自月度统计表第 3 列', 'aria-label': '数据来源说明'
    });
    dataLine.append(node('small', '数据型字段未配置取数来源前会进入「待配数据来源」清单。'), dataNote);
    const toggleOwner = () => { dataLine.style.display = ownerData.checked ? 'flex' : 'none'; };
    ownerWriter.onchange = toggleOwner;
    ownerData.onchange = toggleOwner;

    const actions = node('div', null, { class: 'td-custom-actions' });
    actions.style.cssText = 'display:flex;gap:8px;justify-content:flex;margin-top:2px';
    const confirm = node('button', '生成自定义字段', { type: 'button', class: 'primary' });
    const cancel = node('button', '取消', { type: 'button' });
    cancel.onclick = () => { form.remove(); if (groups) groups.style.display = ''; if (foot) foot.style.display = ''; };
    confirm.onclick = () => busy(confirm, async () => {
      const displayName = nameInput.value.trim();
      const semantic = semanticInput.value.trim();
      if (!displayName) throw Error('请填写字段显示名（1~20 字）。');
      if (displayName.length > 20) throw Error('字段显示名最多 20 个字。');
      if (!semantic) throw Error('请用一句话说明这个字段的含义（告诉 Writer 这个字段怎么填）。');
      const owner = ownerData.checked ? 'data' : 'writer';
      // data_note 只随「程序按数据算」提交；切回 writer 不带（后端也会再丢弃一次）。
      const definition = { display_name: displayName, semantic, owner };
      if (owner === 'data') definition.data_note = dataNote.value.trim();
      await submit(block, text, start, 'custom_text', definition);
    });
    actions.append(cancel, confirm);

    form.append(node('label', '字段显示名', { style: 'font-size:11px;color:var(--muted)' }), nameInput,
      node('label', '字段含义 / 语义', { style: 'font-size:11px;color:var(--muted)' }), semanticInput,
      ownerLine, dataLine, actions);
    card.append(form);
    // 展开表单后卡片可能超出视口底部：重新定位，保持整卡在屏内。
    requestAnimationFrame(() => {
      card.style.top = Math.max(8, Math.min(parseInt(card.style.top || '0', 10),
        window.innerHeight - card.offsetHeight - 8)) + 'px';
      nameInput.focus();
    });
  }

  /* ---------------------------------------------------------------- 提交 */
  async function submit(block, text, start, choice, custom) {
    const payload = {
      expected_revision: S.revision,
      block: Number(block.index),
      selected_text: text || '',
      start: start || 0,
      choice
    };
    if (custom) payload.custom = custom;
    const data = await call(`/api/templates/${S.taskId}/draft/selection`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
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

  /* ------------------------------------------------- 三轮研判终审参考意见 */
  // 三轮模板语义研判的最后一轮意见随候选工件一起返回（human_review_items）：
  // 第二轮完美时是第二轮意见，否则是第三轮意见。全部 advisory——只展示，
  // 没有「接受/应用」动作，不阻塞「确认并保存模板」；要改仍走手动定义或重新研判。
  const H = { taskId: null, definition: null, container: null, pendingLocate: undefined, locateTimer: null };

  function humanReviewFieldLabel(fieldId) {
    const field = (H.definition?.fields || []).find(item => item.id === fieldId);
    return field ? (field.display_name || field.id) : (fieldId || '整份模板');
  }

  function reviewTarget(root, fieldId) {
    if (!root) return null;
    if (fieldId) {
      const chip = Array.from(root.querySelectorAll('.field-chip')).find(el => el.dataset.field === fieldId);
      if (chip) return chip;
      const blocks = H.definition?.blocks || S.definition?.blocks || [];
      const block = blocks.find(item => (item.parts || []).some(part => part.field === fieldId));
      if (block) return root.querySelector('[data-block="' + String(block.index) + '"]');
      return null;
    }
    return root.querySelector('.report-paper');
  }

  function clearLocateHighlight(root) {
    (root || document).querySelectorAll('.td-chip-locate').forEach(el => el.classList.remove('td-chip-locate'));
  }

  function applyLocate(target) {
    const root = H.container || S.container;
    clearLocateHighlight(root);
    target.classList.add('td-chip-locate');
    target.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
    if (H.locateTimer) clearTimeout(H.locateTimer);
    H.locateTimer = setTimeout(() => target.classList.remove('td-chip-locate'), 2600);
  }

  function flushPendingLocate() {
    if (H.pendingLocate === undefined) return;
    const fieldId = H.pendingLocate;
    H.pendingLocate = undefined;
    const root = H.container || S.container;
    const target = reviewTarget(root, fieldId);
    if (target) applyLocate(target);
    else toast(fieldId ? '正文里没有找到这个字段的位置。' : '当前页没有模板正文，请先打开模型研判后的模板再定位。');
  }

  function locateHumanReviewField(fieldId) {
    const root = H.container || S.container;
    const target = reviewTarget(root, fieldId);
    if (target) {
      H.pendingLocate = undefined;
      applyLocate(target);
      return;
    }
    const paper = root && root.querySelector('.report-paper');
    const onCandidatePreview = !!(paper && (root.querySelector('.field-chip') || root.querySelector('[data-block]')));
    if (onCandidatePreview) {
      toast(fieldId ? '正文里没有找到这个字段的位置。' : '当前页没有模板正文，请先打开模型研判后的模板再定位。');
      return;
    }
    const tabBar = root && root.previousElementSibling;
    const firstTab = tabBar && tabBar.classList.contains('review-tabs') ? tabBar.querySelector('button') : null;
    if (firstTab && H.pendingLocate === undefined) {
      H.pendingLocate = fieldId || '';
      firstTab.click();
      return;
    }
    H.pendingLocate = undefined;
    toast(fieldId ? '正文里没有找到这个字段的位置。' : '当前页没有模板正文，请先打开模型研判后的模板再定位。');
  }

  function renderHumanReview(host, container, definition) {
    host.querySelectorAll(':scope > .td-human-review').forEach(element => element.remove());
    const items = Array.isArray(definition?.human_review_items) ? definition.human_review_items : [];
    if (!items.length) return;
    const panel = node('div', null, { class: 'td-advice td-human-review' });
    const head = node('div', null, { class: 'td-advice-head' });
    head.append(node('strong', `模型终审参考意见 ${items.length} 条`));
    head.append(node('span', '这些是模型的参考意见，可忽略，不要求逐条处理。', { class: 'td-advice-readonly' }));
    panel.append(head);
    // 只分两级展示：重要（仅供参考，红）/ 建议（灰）。
    const groups = [
      { label: '重要（仅供参考）', cls: 'td-important', items: items.filter(item => item.severity === '重要') },
      { label: '建议', cls: 'td-suggest', items: items.filter(item => item.severity !== '重要') }
    ];
    for (const group of groups) {
      if (!group.items.length) continue;
      const section = node('div', null, { class: 'td-advice-group ' + group.cls });
      section.append(node('h4', `${group.label}（${group.items.length}）`));
      const list = node('ul');
      for (const item of group.items) {
        const li = node('li');
        if (item.checklist) li.append(node('span', item.checklist, { class: 'td-advice-field' }));
        li.append(node('p', item.message || '', { class: 'td-advice-msg' }));
        const row = node('div', null, { class: 'td-advice-locate-row' });
        row.append(node('span', humanReviewFieldLabel(item.field_id), { class: 'td-advice-field' }));
        const locate = node('button', '定位', { type: 'button', class: 'td-advice-locate' });
        locate.setAttribute('aria-label', '定位到正文中的「' + humanReviewFieldLabel(item.field_id) + '」');
        locate.onclick = () => locateHumanReviewField(item.field_id);
        row.append(locate);
        li.append(row);
        if (item.evidence) li.append(node('blockquote', '原文依据：' + item.evidence, { class: 'td-advice-evidence' }));
        list.append(li);
      }
      section.append(list);
      panel.append(section);
    }
    // 紧跟模板预览之后，renderPaper() 的 container.replaceChildren() 不会清掉它。
    host.insertBefore(panel, container.nextSibling);
    flushPendingLocate();
  }

  async function mountHumanReview({ taskId, container }) {
    H.taskId = taskId;
    H.container = container;
    // 面板作为 container 的兄弟节点，renderPaper() 的 container.replaceChildren() 不会清掉它。
    const host = container.parentElement || container;
    try {
      H.definition = (await api(`/api/templates/${taskId}/definition`)).definition;
    } catch {
      H.definition = null;
      return;
    }
    renderHumanReview(host, container, H.definition);
  }

  /* ---------------------------------------------------------------- 挂载 */
  async function mount({ taskId, container, onField, onRevision, confirmed } = {}) {
    if (!taskId || !container) return;
    if (confirmed) {
      // 已确认模板不可再手动定义：只只读展示三轮研判的终审参考意见。
      await mountHumanReview({ taskId, container });
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
    // 终审参考意见随候选工件返回：只读展示在预览下方，不阻塞确认按钮。
    void mountHumanReview({ taskId, container });
  }

  window.TemplateDraft = { mount, canonText, canonOffset, choices: () => S.choices };
})();
