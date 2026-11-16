/* 终稿编辑页（canvas-editor）
 * 载入：优先 GET /api/tasks/<id>/final-docx（存回系统的编辑版）；
 *       没有时回退老的「metadata 找 draft_ref → /api/artifacts/<ref>/download」。
 * 保存：插件 executeExportDocx 返回 Blob（canvas-editor 1.2.0 的 A2 实现是
 *       `return E2(blob, name), blob`），拿到 Blob → POST /api/tasks/<id>/final-docx。
 *       插件导出时还会同步创建一个 <a download> 并 click；为了「保存」不弹另存为，
 *       这里在导出期间短暂拦截插件自己那个带 download 属性的下载锚，结束立刻恢复。
 * 导出：仍走浏览器下载（插件原生行为，不拦截）。
 *
 * 命令名与枚举均已核对（canvas-editor 1.2.0）：
 *   executeUndo/Redo/Bold/Italic/Underline/Strikeout
 *   executeSizeAdd/executeSizeMinus/executeSize
 *   executeRowFlex(RowFlex.LEFT|CENTER|RIGHT|ALIGNMENT)
 *   executeTitle(TitleLevel.FIRST|SECOND|'')  executeList(ListType.UL|OL)
 *   executeInsertTable(row, col)  executePrint
 *   executeImportDocx({arrayBuffer}) / executeExportDocx({fileName}) -> Promise<Blob>
 */
(function () {
  'use strict';

  var DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

  var API = window.KNCanvas;
  var msgEl = document.getElementById('edMsg');
  var statusEl = document.getElementById('edStatus');
  var nameEl = document.getElementById('edTaskName');
  var savedEl = document.getElementById('edSavedText');
  var saveBtn = document.getElementById('edSave');

  function say(t) { msgEl.textContent = t || '—'; }
  function status(t) { statusEl.textContent = t; }
  function setSaved(t) { if (savedEl) savedEl.textContent = t; }

  function hhmm(value) {
    var d = value instanceof Date ? value : new Date(value);
    if (isNaN(d.getTime())) return '--:--';
    return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
  }

  if (!API || !API.Editor) { say('编辑器脚本未加载'); return; }

  var params = new URLSearchParams(location.search);
  var taskId = params.get('task') || '';
  if (taskId) nameEl.textContent = taskId;

  // ── 初始化（选项与已验证的探针一致；缺 width/height/pageMode 会渲染异常）──
  var instance = new API.Editor(document.getElementById('ceContainer'), {
    defaultSize: 16,
    defaultFont: 'Microsoft YaHei',
    defaultColor: '#141413',
    margins: [60, 70, 60, 70],
    pageMode: true,
    width: 794,
    height: 1123,
    main: [{ value: '' }]
  });
  instance.use(API.docxPlugin);

  var cmd = instance.command;
  // 调试/自测钩子：外部（CDP 断言、控制台）需要 getValue() 核对真实排版结果。
  window.__edEditor = instance;

  // ── 工具栏 ───────────────────────────────────────────────────
  var barEl = document.querySelector('.ed-bar');

  // 点工具栏按钮不把焦点从编辑器抢走：否则「点 B → 接着打字」会把字打到按钮上。
  // 只拦 mousedown 的默认动作（焦点转移），click 与视觉反馈不受影响。
  barEl.addEventListener('mousedown', function (event) {
    if (event.target.closest('.ed-btn, .ed-mi')) event.preventDefault();
  });

  barEl.addEventListener('click', function (event) {
    var btn = event.target.closest('.ed-btn, .ed-mi');
    if (!btn || btn.disabled) return;
    if (btn.id === 'edMoreBtn') { toggleMore(); return; }
    var isItem = btn.classList.contains('ed-mi');
    var d = btn.dataset;
    if (!d.cmd && !d.size && !d.align && !d.title && !d.list && !d.table) {
      // 载入模板 / 载入报告 走各自监听器；无论哪条路，点了菜单项就收起菜单。
      if (isItem) closeMore();
      return;
    }
    try {
      if (d.cmd) { cmd[d.cmd](); }
      else if (d.size === '+') { cmd.executeSizeAdd(); }
      else if (d.size === '-') { cmd.executeSizeMinus(); }
      else if (d.align) { cmd.executeRowFlex(d.align); }
      else if (d.title) { cmd.executeTitle(d.title === 'p' ? '' : d.title); }
      else if (d.list) { cmd.executeList(d.list); }
      else if (d.table) { cmd.executeInsertTable(3, 3); }
      status('已执行');
    } catch (err) {
      status('命令不支持: ' + (d.cmd || d.align || d.title || d.list || ''));
    }
    if (isItem) closeMore();
  });

  // ── 「更多」菜单 ─────────────────────────────────────────────
  // 6 个低频命令（列表×2 / 插表格 / 载入×2 / 打印）在左栏占掉 240px 后放不进
  // 一行，收进最右侧「更多」。菜单项与工具栏共用同一套 data-* 契约，所以命令
  // 派发仍走上面那个委托口；.ed-mi 也沿用 .ed-btn 的 .on + aria-pressed 按下态，
  // 状态由已有的 rangeStyleChange（applyRangeStyle）直接写，不需要第二份同步逻辑。
  var moreBtn = document.getElementById('edMoreBtn');
  var morePanel = document.getElementById('edMorePanel');

  function moreOpen() { return barEl.classList.contains('more-open'); }
  function openMore() {
    barEl.classList.add('more-open');
    if (moreBtn) moreBtn.setAttribute('aria-expanded', 'true');
  }
  function closeMore() {
    barEl.classList.remove('more-open');
    if (moreBtn) moreBtn.setAttribute('aria-expanded', 'false');
  }
  function toggleMore() { if (moreOpen()) { closeMore(); } else { openMore(); } }

  // 点面板外关闭。用捕获阶段：画布（canvas-editor）会吃掉自己那侧的冒泡，
  // 冒泡监听在画布上点一下收不起菜单。
  document.addEventListener('click', function (event) {
    if (!moreOpen()) return;
    var t = event.target;
    if (!t || !t.closest) return;
    if (morePanel && morePanel.contains(t)) return;
    if (moreBtn && moreBtn.contains(t)) return;
    closeMore();
  }, true);

  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape' && event.key !== 'Esc') return;
    if (!moreOpen()) return;
    closeMore();
    if (moreBtn) moreBtn.focus();
    event.preventDefault();
  });

  // ── 工具栏按下态（事件驱动）────────────────────────────────────
  // 依据（@hufe921/canvas-editor dist 类型定义 + vendor bundle 实测）：
  //   instance.eventBus.on('rangeStyleChange', cb)  事件总线，payload = IRangeStyle
  //   instance.listener.rangeStyleChange = cb       同一 payload 的 options 回调口（备用）
  //   instance.command.getRangeContext()            手动查（本页不用，太重）
  //   IRangeStyle = { type, undo, redo, painter, font, size,
  //                   bold, italic, underline, strikeout, color, highlight,
  //                   rowFlex, level, listType, ... }
  //   编辑器每次 render 之后在 rAF 里调 range.setRangeStyle() 派发。
  //   recoveryRangeStyle()（失焦/离开画布）派发的 payload 里 type === null，
  //   正常 payload 的 type 恒为 'text'/'table'/…；据此丢弃重置包，
  //   免得点完按钮状态被整体清零（点击路径同帧会先来一个重置包）。
  var TOGGLE = {
    bold: barEl.querySelector('[data-cmd="executeBold"]'),
    italic: barEl.querySelector('[data-cmd="executeItalic"]'),
    underline: barEl.querySelector('[data-cmd="executeUnderline"]'),
    strikeout: barEl.querySelector('[data-cmd="executeStrikeout"]'),
    alignLeft: barEl.querySelector('[data-align="left"]'),
    alignCenter: barEl.querySelector('[data-align="center"]'),
    alignRight: barEl.querySelector('[data-align="right"]'),
    alignJustify: barEl.querySelector('[data-align="alignment"]'),
    titleFirst: barEl.querySelector('[data-title="first"]'),
    titleSecond: barEl.querySelector('[data-title="second"]'),
    titleP: barEl.querySelector('[data-title="p"]'),
    listUl: barEl.querySelector('[data-list="ul"]'),
    listOl: barEl.querySelector('[data-list="ol"]')
  };

  function mark(btn, on) {
    if (!btn) return;
    if (on) { btn.classList.add('on'); } else { btn.classList.remove('on'); }
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
  }

  function applyRangeStyle(st) {
    if (!st || st.type == null) return;
    mark(TOGGLE.bold, !!st.bold);
    mark(TOGGLE.italic, !!st.italic);
    mark(TOGGLE.underline, !!st.underline);
    mark(TOGGLE.strikeout, !!st.strikeout);

    // rowFlex 为空 = 左对齐（canvas-editor 的默认值）
    var flex = st.rowFlex || 'left';
    mark(TOGGLE.alignLeft, flex === 'left');
    mark(TOGGLE.alignCenter, flex === 'center');
    mark(TOGGLE.alignRight, flex === 'right');
    mark(TOGGLE.alignJustify, flex === 'alignment' || flex === 'justify');

    // level 为空 = 正文；third…sixth 不在本工具栏的三档内，故三颗都不亮
    var level = st.level || '';
    mark(TOGGLE.titleFirst, level === 'first');
    mark(TOGGLE.titleSecond, level === 'second');
    mark(TOGGLE.titleP, level === '');

    mark(TOGGLE.listUl, st.listType === 'ul');
    mark(TOGGLE.listOl, st.listType === 'ol');
  }

  if (instance.eventBus && typeof instance.eventBus.on === 'function') {
    instance.eventBus.on('rangeStyleChange', applyRangeStyle);
  } else if (instance.listener) {
    instance.listener.rangeStyleChange = applyRangeStyle;
  }

  // ── 载入 docx ────────────────────────────────────────────────
  function importBuffer(buf, label) {
    cmd.executeImportDocx({ arrayBuffer: buf });
    say('已载入 ' + label + ' · ' + (buf.byteLength / 1024).toFixed(0) + ' KB');
    status('已载入');
  }

  function loadFrom(url, label) {
    say('正在载入 ' + label + '…'); status('载入中');
    fetch(url)
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.arrayBuffer(); })
      .then(function (buf) { importBuffer(buf, label); })
      .catch(function (err) { say('载入失败：' + err.message); status('载入失败'); });
  }

  // 优先取存回系统的编辑版；非 200 才回退到「metadata 找 draft_ref → artifact 下载」。
  function loadTaskDocx(id) {
    fetch('/api/tasks/' + encodeURIComponent(id))
      .then(function (r) { return r.json(); })
      .then(function (task) {
        var md = task.metadata || {};
        nameEl.textContent = task.display_name || id;
        say('正在载入编辑版…'); status('载入中');
        return fetch('/api/tasks/' + encodeURIComponent(id) + '/final-docx')
          .then(function (r) { return r.ok ? r.arrayBuffer() : null; })
          .then(function (buf) {
            if (buf) { importBuffer(buf, '编辑版 docx'); return; }
            var ref = md.draft_ref || md.docx_ref;
            if (!ref) { say('该任务没有可载入的 docx 产物'); status('无产物'); return; }
            loadFrom('/api/artifacts/' + encodeURIComponent(ref) + '/download', '报告 docx');
          });
      })
      .catch(function (err) { say('任务详情读取失败：' + err.message); status('载入失败'); });
  }

  document.getElementById('edLoadTpl').addEventListener('click', function () {
    loadFrom('/api/template-docx', '模板 docx');
  });

  document.getElementById('edLoadDoc').addEventListener('click', function () {
    if (taskId) { loadTaskDocx(taskId); return; }
    fetch('/api/tasks')
      .then(function (r) { return r.json(); })
      .then(function (tasks) {
        var list = Array.isArray(tasks) ? tasks : (tasks.tasks || []);
        var hit = list.filter(function (t) { return t.draft; })[0];
        if (!hit) { say('没有已生成的报告可载入'); status('无数据'); return; }
        taskId = hit.id;
        if (nameEl) nameEl.textContent = hit.display_name || hit.id;
        refreshSaved();
        loadTaskDocx(hit.id);
      })
      .catch(function (err) { say('任务列表读取失败：' + err.message); });
  });

  // ── 导出 / 保存 ─────────────────────────────────────────────
  // 插件 A2() 内部固定拼 `${fileName}.docx`（canvas-editor.js: E2(W, `${i}.docx`)），
  // 所以这里只传基名，否则会得到 xxx.docx.docx。
  function fileNameBase() {
    return (taskId || '终稿') + '-' + new Date().toISOString().slice(0, 10);
  }
  function fileName() {
    return fileNameBase() + '.docx';
  }

  // 导出到本地（插件原生下载，不拦截）
  document.getElementById('edExport').addEventListener('click', function () {
    var name = fileName();
    try {
      var maybe = cmd.executeExportDocx({ fileName: fileNameBase() });
      if (maybe && typeof maybe.then === 'function') { maybe.catch(function () {}); }
      say('已导出 ' + name); status('已导出');
    } catch (err) {
      say('导出失败：' + err.message); status('导出失败');
    }
  });

  // 导出但拿到 Blob：插件内部的 E2() 会造一个 <a download> 并立刻 click，
  // 这里在导出期间只拦「带 download 属性的锚」的 click，结束后立即恢复原型。
  // name 同样是「基名」：插件自己补 .docx（这里只用于被拦截的临时锚）。
  function exportBlobSilently(name) {
    var proto = window.HTMLAnchorElement.prototype;
    var original = proto.click;
    proto.click = function () {
      if (this.hasAttribute('download')) { return; }
      return original.apply(this, arguments);
    };
    function restore() { proto.click = original; }
    return Promise.resolve()
      .then(function () { return cmd.executeExportDocx({ fileName: name }); })
      .then(function (blob) { restore(); return blob; },
            function (err) { restore(); throw err; });
  }

  var saving = false;
  if (saveBtn) saveBtn.addEventListener('click', function () {
    if (saving) return;
    if (!taskId) {
      say('保存失败：页面未带 ?task=，不知道该存到哪个任务');
      status('保存失败');
      setSaved('未保存');
      return;
    }
    saving = true; saveBtn.disabled = true;
    say('正在生成 docx 并上传…'); status('保存中');
    exportBlobSilently(fileNameBase())
      .then(function (blob) {
        if (!blob || typeof blob.arrayBuffer !== 'function') {
          throw new Error('插件未返回 docx 字节');
        }
        return blob.arrayBuffer();
      })
      .then(function (buf) {
        return fetch('/api/tasks/' + encodeURIComponent(taskId) + '/final-docx', {
          method: 'POST',
          headers: { 'Content-Type': DOCX_MIME },
          body: buf
        }).then(function (r) {
          return r.text().then(function (text) {
            if (!r.ok) {
              var detail = text;
              try { detail = JSON.parse(text).detail || text; } catch (e) {}
              throw new Error('HTTP ' + r.status + (detail ? ' ' + String(detail).slice(0, 60) : ''));
            }
            var data = {};
            try { data = JSON.parse(text); } catch (e) {}
            say('已保存到系统 · ' + (data.bytes || buf.byteLength) + ' 字节 · sha256 '
                + String(data.sha256 || '').slice(0, 12) + '…');
            status('已保存');
            setSaved('已保存 ' + hhmm(new Date()));
          });
        });
      })
      .catch(function (err) {
        say('保存失败：' + err.message);
        status('保存失败');
        setSaved('保存失败');
      })
      .then(function () { saving = false; if (saveBtn) saveBtn.disabled = false; });
  });

  // ── 打开时读「已保存 / 未保存」 ─────────────────────────────
  function refreshSaved() {
    if (!taskId) { setSaved('未保存'); return; }
    fetch('/api/tasks/' + encodeURIComponent(taskId) + '/final-docx/meta')
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (m) {
        if (m && m.available && m.updated_at) { setSaved('已保存 ' + hhmm(m.updated_at)); }
        else { setSaved('未保存'); }
      })
      .catch(function () { setSaved('未保存'); });
  }

  if (!taskId) {
    setSaved('未保存');
  } else {
    refreshSaved();
    loadTaskDocx(taskId);
  }

  say('就绪 · 载入模板或报告后可编辑、保存到系统或导出');
  status('就绪');

  // ── 左栏「历史生成报告」──────────────────────────────────────
  // 列表只有「有报告的任务」（后端 /api/reports/editable 已判定）；
  // 点条目 = 载入该报告（saved 读编辑版，draft 读产物下载），删除 = 软删（只写时间戳）。
  var listEl = document.getElementById('edReports');

  function mmdd(value) {
    var d = value instanceof Date ? value : new Date(value);
    if (isNaN(d.getTime())) return '--';
    return ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
  }

  function setActive(id) {
    var rows = listEl.querySelectorAll('.ed-rep');
    for (var i = 0; i < rows.length; i++) {
      var on = rows[i].getAttribute('data-id') === id;
      rows[i].classList.toggle('on', on);
      if (on) { rows[i].setAttribute('aria-current', 'true'); }
      else { rows[i].removeAttribute('aria-current'); }
    }
  }

  function closeMenus(keep) {
    var rows = listEl.querySelectorAll('.ed-rep.menu');
    for (var i = 0; i < rows.length; i++) { if (rows[i] !== keep) rows[i].classList.remove('menu'); }
  }

  function renderEmpty() {
    listEl.textContent = '';
    var empty = document.createElement('div');
    empty.className = 'ed-empty';
    empty.textContent = '暂无报告';
    listEl.appendChild(empty);
  }

  function loadReport(item) {
    taskId = item.task_id;
    if (nameEl) nameEl.textContent = item.name || item.task_id;
    setActive(item.task_id);
    refreshSaved();
    say('正在载入 ' + (item.name || item.task_id) + '…'); status('载入中');
    var url = item.url || ('/api/tasks/' + encodeURIComponent(item.task_id) + '/final-docx');
    fetch(url)
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.arrayBuffer(); })
      .then(function (buf) { importBuffer(buf, item.status === 'saved' ? '编辑版 docx' : '报告 docx'); })
      .catch(function (err) { say('载入失败：' + err.message); status('载入失败'); });
  }

  function deleteReport(item, row) {
    say('正在删除 ' + (item.name || item.task_id) + '…'); status('删除中');
    fetch('/api/reports/editable/' + encodeURIComponent(item.task_id), { method: 'DELETE' })
      .then(function (r) {
        return r.text().then(function (text) {
          if (!r.ok) {
            var detail = text;
            try { detail = JSON.parse(text).detail || text; } catch (e) {}
            throw new Error('HTTP ' + r.status + (detail ? ' ' + String(detail).slice(0, 60) : ''));
          }
          var data = {};
          try { data = JSON.parse(text); } catch (e) {}
          row.parentNode.removeChild(row);
          if (!listEl.querySelector('.ed-rep')) renderEmpty();
          say('已删除 ' + (item.name || item.task_id) + ' · '
              + String(data.deleted_at || '').slice(0, 16).replace('T', ' '));
          status('已删除');
        });
      })
      .catch(function (err) { say('删除失败：' + err.message); status('删除失败'); });
  }

  function reportRow(item) {
    var row = document.createElement('div');
    row.className = 'ed-rep';
    row.setAttribute('data-id', item.task_id);
    row.setAttribute('role', 'button');
    row.setAttribute('tabindex', '0');
    row.title = item.name || item.task_id;

    var name = document.createElement('div');
    name.className = 'ed-rep-name';
    name.textContent = item.name || item.task_id;

    var meta = document.createElement('div');
    meta.className = 'ed-rep-meta';
    var date = document.createElement('span');
    date.textContent = mmdd(item.updated_at);
    var st = document.createElement('span');
    st.className = 'st';
    st.textContent = item.status === 'saved' ? '已保存' : '草稿';
    meta.appendChild(date);
    meta.appendChild(st);

    var more = document.createElement('button');
    more.className = 'ed-rep-more';
    more.type = 'button';
    more.title = '更多';
    more.setAttribute('aria-label', '更多操作');
    more.textContent = '⋯';

    var menu = document.createElement('div');
    menu.className = 'ed-rep-menu';
    var del = document.createElement('button');
    del.className = 'del';
    del.type = 'button';
    del.textContent = '删除';
    var cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.textContent = '取消';
    menu.appendChild(del);
    menu.appendChild(cancel);

    row.appendChild(name);
    row.appendChild(meta);
    row.appendChild(more);
    row.appendChild(menu);

    row.addEventListener('click', function (event) {
      if (event.target.closest('.ed-rep-more') || event.target.closest('.ed-rep-menu')) return;
      closeMenus(null);
      loadReport(item);
    });
    row.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); loadReport(item); }
    });
    more.addEventListener('click', function (event) {
      event.stopPropagation();
      var open = row.classList.contains('menu');
      closeMenus(row);
      if (open) { row.classList.remove('menu'); } else { row.classList.add('menu'); }
    });
    cancel.addEventListener('click', function (event) {
      event.stopPropagation();
      row.classList.remove('menu');
    });
    del.addEventListener('click', function (event) {
      event.stopPropagation();
      row.classList.remove('menu');
      deleteReport(item, row);
    });
    return row;
  }

  function renderReports(items) {
    listEl.textContent = '';
    if (!items.length) { renderEmpty(); return; }
    for (var i = 0; i < items.length; i++) { listEl.appendChild(reportRow(items[i])); }
    if (taskId) setActive(taskId);
  }

  function refreshReports() {
    fetch('/api/reports/editable')
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (items) { renderReports(Array.isArray(items) ? items : []); })
      .catch(function () { renderEmpty(); });
  }

  // 点空白处收起行内菜单（不拦截、不冒泡到条目自己的 click）
  document.addEventListener('click', function (event) {
    if (!event.target.closest || !event.target.closest('.ed-rep')) closeMenus(null);
  });

  refreshReports();

  // 测试钩子：?load=tpl 自动载入模板；?load=doc 自动载入报告
  var auto = params.get('load');
  if (auto === 'tpl') { loadFrom('/api/template-docx', '模板 docx'); }
  else if (auto === 'doc') { document.getElementById('edLoadDoc').click(); }
})();
