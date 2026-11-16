/* 终稿编辑页（canvas-editor）
 * 载入：GET /api/template-docx（模板）或 /api/artifacts/<id>/download（已生成报告）
 * 导出：docx 插件生成真 docx，浏览器直接下载
 *
 * 命令名与枚举均已核对（canvas-editor 1.2.0）：
 *   executeUndo/Redo/Bold/Italic/Underline/Strikeout
 *   executeSizeAdd/executeSizeMinus/executeSize
 *   executeRowFlex(RowFlex.LEFT|CENTER|RIGHT|ALIGNMENT)
 *   executeTitle(TitleLevel.FIRST|SECOND|'')  executeList(ListType.UL|OL)
 *   executeInsertTable(row, col)  executePrint
 *   executeImportDocx({arrayBuffer}) / executeExportDocx({fileName})
 */
(function () {
  'use strict';

  var API = window.KNCanvas;
  var msgEl = document.getElementById('edMsg');
  var statusEl = document.getElementById('edStatus');
  var nameEl = document.getElementById('edTaskName');

  function say(t) { msgEl.textContent = t || '—'; }
  function status(t) { statusEl.textContent = t; }

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

  // ── 工具栏 ───────────────────────────────────────────────────
  var cmd = instance.command;
  document.querySelector('.ed-bar').addEventListener('click', function (event) {
    var btn = event.target.closest('.ed-btn');
    if (!btn || btn.disabled) return;
    var d = btn.dataset;
    try {
      if (d.cmd) { cmd[d.cmd](); }
      else if (d.size === '+') { cmd.executeSizeAdd(); }
      else if (d.size === '-') { cmd.executeSizeMinus(); }
      else if (d.align) { cmd.executeRowFlex(d.align); }
      else if (d.title) { cmd.executeTitle(d.title === 'p' ? '' : d.title); }
      else if (d.list) { cmd.executeList(d.list); }
      else if (d.table) { cmd.executeInsertTable(3, 3); }
      else { return; }
      status('已执行');
    } catch (err) {
      status('命令不支持: ' + (d.cmd || d.align || d.title || d.list || ''));
    }
  });

  // ── 载入 docx ────────────────────────────────────────────────
  function loadFrom(url, label) {
    say('正在载入 ' + label + '…'); status('载入中');
    fetch(url)
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.arrayBuffer(); })
      .then(function (buf) {
        cmd.executeImportDocx({ arrayBuffer: buf });
        say('已载入 ' + label + ' · ' + (buf.byteLength / 1024).toFixed(0) + ' KB');
        status('已载入');
        })
      .catch(function (err) { say('载入失败：' + err.message); status('载入失败'); });
  }

  function loadTaskDocx(id) {
    fetch('/api/tasks/' + encodeURIComponent(id))
      .then(function (r) { return r.json(); })
      .then(function (task) {
        var md = task.metadata || {};
        var ref = md.draft_ref || md.final_docx_ref || md.docx_ref;
        nameEl.textContent = task.display_name || id;
        if (!ref) { say('该任务没有可载入的 docx 产物'); status('无产物'); return; }
        loadFrom('/api/artifacts/' + encodeURIComponent(ref) + '/download', '报告 docx');
      })
      .catch(function (err) { say('任务详情读取失败：' + err.message); });
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
        loadTaskDocx(hit.id);
      })
      .catch(function (err) { say('任务列表读取失败：' + err.message); });
  });

  // ── 导出 ────────────────────────────────────────────────────
  document.getElementById('edExport').addEventListener('click', function () {
    var name = (taskId || '终稿') + '-' + new Date().toISOString().slice(0, 10) + '.docx';
    try {
      cmd.executeExportDocx({ fileName: name });
      say('已导出 ' + name); status('已导出');
    } catch (err) {
      say('导出失败：' + err.message); status('导出失败');
    }
  });

  say('就绪 · 载入模板或报告后可编辑导出');
  status('就绪');

  // 测试钩子：?load=tpl 自动载入模板；?load=doc 自动载入最新报告
  var auto = params.get('load');
  if (auto === 'tpl') { loadFrom('/api/template-docx', '模板 docx'); }
  else if (auto === 'doc') { document.getElementById('edLoadDoc').click(); }
})();
