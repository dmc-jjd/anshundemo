/* 终稿人工审核页（方案 3：自研 A4 页 + contenteditable）。
 * 纪律：只有「编辑占位符内容」一种操作——无富文本工具栏；图表只显示、不可编辑。
 * 数据：GET /api/tasks/{id}/final-document 的渲染模型；保存走 POST …/save，
 *      只提交前端 diff 出来的变化槽，并带 expected_revision 防并发。
 * 修改日志：GET …/versions（倒序），抽屉里逐条列出 before → after。 */
(function () {
  'use strict';

  var params = new URLSearchParams(window.location.search);
  var taskId = params.get('task') || '';
  var WRITABLE = ['awaiting_final_review', 'facts_frozen'];
  var CHART_TITLES = {
    sentiment: '图1 舆情情绪分布图',
    daily: '图2 舆情信息数量图',
    platform: '图3 舆情信源分布图',
    theme: '图4 负面舆情分类分布情况',
    locality: '图5 各区县舆情分布情况'
  };

  var $ = function (selector) { return document.querySelector(selector); };
  var model = null;
  var initial = new Map();   // slot id -> 载入时的值（用于 diff）
  var dirty = new Map();     // slot id -> 当前编辑值（仅变化项）
  var saving = false;

  function toast(text) {
    var node = $('#toast');
    node.textContent = text;
    node.classList.add('show');
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(function () { node.classList.remove('show'); }, 2600);
  }

  function api(path, options) {
    var config = Object.assign({ headers: { 'Content-Type': 'application/json' } }, options || {});
    return fetch(path, config).then(function (response) {
      return response.json().catch(function () { return null; }).then(function (body) {
        if (!response.ok) {
          var error = new Error((body && body.detail) || ('HTTP ' + response.status));
          error.status = response.status;
          error.body = body;
          throw error;
        }
        return body;
      });
    });
  }

  function status(text) { $('#fdStatus').textContent = text; }

  function slotNodes(slotId) {
    return Array.prototype.slice.call(document.querySelectorAll('[data-slot="' + slotId + '"]'));
  }

  function syncSlot(slotId, text) {
    slotNodes(slotId).forEach(function (node) {
      if (node.textContent !== text) node.textContent = text;
    });
  }

  function markSlot(slotId, edited) {
    slotNodes(slotId).forEach(function (node) {
      if (edited) node.dataset.edited = '1'; else delete node.dataset.edited;
    });
  }

  function slotElement(part, editable) {
    var span = document.createElement('span');
    span.className = 'fd-slot';
    span.dataset.slot = part.id;
    span.dataset.code = part.code || 'text';
    if (part.edited) span.dataset.edited = '1';
    var canEdit = editable !== false && part.editable !== false;
    if (canEdit) {
      span.contentEditable = 'true';
      span.spellcheck = false;
      span.setAttribute('role', 'textbox');
      span.setAttribute('aria-label', '槽位 ' + part.id);
    } else {
      span.dataset.fixed = '1';
      span.setAttribute('title', '该槽位由图表/固定内容决定，不可编辑');
    }
    span.textContent = part.value;
    initial.set(part.id, part.value);
    return span;
  }

  function fillParts(parts, container, editable) {
    parts.forEach(function (part) {
      if (part.type === 'slot') container.appendChild(slotElement(part, editable));
      else container.appendChild(document.createTextNode(part.text));
    });
    return container;
  }

  function blockText(block) {
    if (block.text) return block.text;
    var parts = block.parts || [];
    return parts.map(function (part) { return part.type === 'slot' ? part.value : part.text; }).join('');
  }

  function isPlainText(text) {
    return !text || text.indexOf('{{') < 0;
  }

  function renderChart(block) {
    var figure = document.createElement('figure');
    figure.className = 'fd-figure';
    if (block.png_data_url) {
      var image = document.createElement('img');
      image.src = block.png_data_url;
      image.alt = CHART_TITLES[block.name] || ('图表 ' + block.name);
      image.loading = 'lazy';
      figure.appendChild(image);
    } else {
      var missing = document.createElement('div');
      missing.className = 'fd-figure-missing';
      missing.textContent = '图表暂不可用（' + (CHART_TITLES[block.name] || block.name) + '）';
      figure.appendChild(missing);
    }
    return figure;
  }

  function renderTable(block) {
    var table = document.createElement('table');
    table.className = 'fd-table';
    var body = document.createElement('tbody');
    block.rows.forEach(function (row) {
      var tr = document.createElement('tr');
      row.forEach(function (cell) {
        var td = document.createElement('td');
        if (cell.type === 'mixed') fillParts(cell.parts || [], td);
        else if (cell.type === 'slot') td.appendChild(slotElement(cell));
        else td.appendChild(document.createTextNode(cell.text || ''));
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    table.appendChild(body);
    return table;
  }

  function renderParagraph(block, className) {
    var paragraph = document.createElement('p');
    paragraph.className = className || 'fd-p';
    fillParts(block.parts || [], paragraph);
    return paragraph;
  }

  function bodyClass(block, position) {
    var text = blockText(block).trim();
    if (block.kind === 'preamble') return 'fd-preamble';
    if (/^[一二三四五六七八九十]+、/.test(text)) return 'fd-h2';
    if (/^（[一二三四五六七八九十]+）/.test(text)) return 'fd-h3';
    if (/^图\s*\d/.test(text) || /^表\s*\d/.test(text)) return 'fd-caption';
    if (position === 0 && text.indexOf('网络舆情分析报告') >= 0) return 'fd-title';
    if (position < 4 && isPlainText(text)) return 'fd-cover';
    return 'fd-p';
  }

  function renderDefinition(blocks, host) {
    host.textContent = '';
    blocks.forEach(function (block) {
      var row = document.createElement('div');
      row.className = 'fd-def-row';
      if (block.kind === 'paragraph') fillParts(block.parts || [], row, true);
      else if (block.kind === 'table') row.appendChild(renderTable(block));
      host.appendChild(row);
    });
  }

  function countEdited() {
    var touched = new Set(Object.keys((model && model.overrides) || {}));
    dirty.forEach(function (text, slotId) { touched.add(slotId); });
    return touched.size;
  }

  function updateBar() {
    $('#fdEdited').textContent = '已改 ' + countEdited() + ' 处';
    $('#fdVersion').textContent = 'v' + ((model && model.revision) || 0);
  }

  function render(modelData) {
    model = modelData;
    initial = new Map();
    dirty = new Map();
    $('#fdTaskId').textContent = taskId;
    $('#fdPhase').textContent = model.phase || '—';
    var definition = model.sections[0] || { blocks: [], count: 0 };
    var body = model.sections[1] || { blocks: [], count: 0 };
    $('#fdDefCount').textContent = definition.count || definition.blocks.length;
    renderDefinition(definition.blocks || [], $('#fdDefBody'));

    var sheet = $('#fdSheet');
    sheet.textContent = '';
    var preambles = (body.blocks || []).filter(function (block) { return block.kind === 'preamble'; });
    var position = 0;
    (body.blocks || []).forEach(function (block) {
      if (block.kind === 'preamble') return;
      if (block.kind === 'chart') {
        sheet.appendChild(renderChart(block));
        position += 1;
        return;
      }
      if (block.kind === 'table') {
        sheet.appendChild(renderTable(block));
        position += 1;
        return;
      }
      sheet.appendChild(renderParagraph(block, bodyClass(block, position)));
      position += 1;
    });
    if (preambles.length) {
      var notes = document.createElement('div');
      notes.className = 'fd-sheet-notes';
      preambles.forEach(function (block) {
        var note = document.createElement('p');
        note.className = 'fd-note';
        note.textContent = blockText(block);
        notes.appendChild(note);
      });
      $('#fdDefBody').appendChild(notes);
    }
    var editable = WRITABLE.indexOf(model.phase) >= 0;
    sheet.classList.toggle('fd-readonly', !editable);
    $('#fdSave').disabled = !editable;
    status(editable ? '可编辑 · 保存后生成新版本' : '当前阶段只读');
    updateBar();
  }

  function markDirty(slotId, text) {
    if (text === (initial.get(slotId) || '')) dirty.delete(slotId);
    else dirty.set(slotId, text);
    syncSlot(slotId, text);
    var stored = (model && model.overrides) || {};
    markSlot(slotId, dirty.has(slotId) || stored[slotId] !== undefined);
    updateBar();
  }

  function onInput(event) {
    var node = event.target.closest('.fd-slot[contenteditable="true"]');
    if (!node) return;
    markDirty(node.dataset.slot, node.textContent || '');
  }

  function onPaste(event) {
    var node = event.target.closest('.fd-slot[contenteditable="true"]');
    if (!node) return;
    event.preventDefault();
    var text = (event.clipboardData || window.clipboardData).getData('text/plain') || '';
    document.execCommand('insertText', false, text);
  }

  function onKeyDown(event) {
    var node = event.target.closest('.fd-slot[contenteditable="true"]');
    if (!node) return;
    if (event.key === 'Enter') event.preventDefault();  // 槽位保持单段文本，不产生富文本结构
  }

  function save() {
    if (saving || !model) return;
    var values = {};
    dirty.forEach(function (text, slotId) {
      if (text !== (initial.get(slotId) || '')) values[slotId] = text;
    });
    if (!Object.keys(values).length) { toast('没有新的修改'); return; }
    saving = true;
    $('#fdSave').disabled = true;
    status('正在保存…');
    api('/api/tasks/' + encodeURIComponent(taskId) + '/final-document/save', {
      method: 'POST',
      body: JSON.stringify({ values: values, expected_revision: model.revision })
    }).then(function (result) {
      saving = false;
      if (!result.changed) { toast('没有需要保存的修改'); }
      else { toast('已保存为 v' + result.version_no + '（' + result.changed_count + ' 处）'); }
      return load();
    }).catch(function (error) {
      saving = false;
      $('#fdSave').disabled = false;
      if (error.status === 409 && error.message === 'stale_final_document') {
        toast('终稿已被更新，正在重新载入');
        return load();
      }
      status('保存失败：' + error.message);
      toast('保存失败：' + error.message);
      return null;
    });
  }

  function formatTime(value) {
    if (!value) return '—';
    var date = new Date(value);
    if (isNaN(date.getTime())) return value;
    return date.toLocaleString('zh-CN', { hour12: false });
  }

  function renderLog(payload) {
    var host = $('#fdDrawerBody');
    host.textContent = '';
    var versions = payload.versions || [];
    if (!versions.length) {
      var empty = document.createElement('p');
      empty.className = 'fd-log-empty';
      empty.textContent = '还没有人工修改记录。';
      host.appendChild(empty);
      return;
    }
    versions.forEach(function (version) {
      var item = document.createElement('section');
      item.className = 'fd-log-item';
      var head = document.createElement('div');
      head.className = 'fd-log-head';
      var label = document.createElement('strong');
      label.textContent = 'v' + version.version_no;
      head.appendChild(label);
      var meta = document.createElement('span');
      meta.textContent = (version.kind === 'reset' ? '还原计算值' : '人工保存') +
        ' · 改 ' + version.changed_count + ' 处 · ' + formatTime(version.saved_at);
      head.appendChild(meta);
      item.appendChild(head);
      var list = document.createElement('ul');
      list.className = 'fd-log-changes';
      var shorten = function (text) {
        var value = String(text == null ? '' : text);
        return value.length > 96 ? value.slice(0, 96) + '…' : value;
      };
      (version.changes || []).forEach(function (change) {
        var li = document.createElement('li');
        var code = document.createElement('code');
        code.textContent = change.slot;
        li.appendChild(code);
        li.appendChild(document.createTextNode('：' + shorten(change.before) + ' → ' + shorten(change.after)));
        list.appendChild(li);
      });
      item.appendChild(list);
      host.appendChild(item);
    });
  }

  function openLog() {
    var drawer = $('#fdDrawer');
    drawer.hidden = false;
    $('#fdDrawerBody').textContent = '正在读取修改日志…';
    api('/api/tasks/' + encodeURIComponent(taskId) + '/final-document/versions')
      .then(renderLog)
      .catch(function (error) { $('#fdDrawerBody').textContent = '读取失败：' + error.message; });
  }

  function load() {
    if (!taskId) {
      status('缺少 task 参数');
      $('#fdSheet').innerHTML = '<p class="fd-loading">请在地址后附加 <code>?task=&lt;任务ID&gt;</code>。</p>';
      return Promise.resolve();
    }
    return api('/api/tasks/' + encodeURIComponent(taskId) + '/final-document')
      .then(function (payload) { render(payload); })
      .catch(function (error) {
        status('载入失败：' + error.message);
        $('#fdSheet').innerHTML = '<p class="fd-loading">载入失败：' + error.message + '</p>';
      });
  }

  document.addEventListener('DOMContentLoaded', function () {
    $('#fdSheet').addEventListener('input', onInput);
    $('#fdSheet').addEventListener('paste', onPaste);
    $('#fdSheet').addEventListener('keydown', onKeyDown);
    $('#fdDefBody').addEventListener('input', onInput);
    $('#fdDefBody').addEventListener('paste', onPaste);
    $('#fdDefBody').addEventListener('keydown', onKeyDown);
    $('#fdSave').addEventListener('click', save);
    $('#fdLog').addEventListener('click', openLog);
    $('#fdDrawerClose').addEventListener('click', function () { $('#fdDrawer').hidden = true; });
    load();
  });
})();
