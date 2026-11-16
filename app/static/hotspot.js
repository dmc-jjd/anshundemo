/* 首页两个新模块：今日热点话题（联网采集，20 条 + 类别 TAB 客户端筛选）+ 社媒热榜（4 tab 占位）。
 *
 * 缓存语义：进入页面只读 `GET /api/hotspot`（不刷新）；**只有点按钮**才 `POST /api/hotspot/collect`
 * 重新采集。失败只在模块内显示一行错误码（红字），不弹窗、不清空既有列表。
 * 类别 TAB：类别清单来自接口返回体的 `categories`（客户包词表），JS 不写死任何类别名；
 * 首项固定「全部」，点击只做客户端过滤——不重新请求、不重新采集。
 * 数据全部走 textContent 写入，不拼 innerHTML——标题与摘要来自外部来源，一律当文本。
 */
(function () {
  var ALL = '全部';

  function pad(n) { return String(n).padStart(2, '0'); }
  function clock(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return pad(d.getHours()) + ':' + pad(d.getMinutes());
  }
  function shortDate(iso) {
    // '2026-11-10' → '11-10'（窗口两端只显示月日）
    if (typeof iso !== 'string' || iso.length < 10) return '—';
    return iso.slice(5, 10);
  }
  function windowLabel(window) {
    window = window || {};
    return '窗口 ' + shortDate(window.from) + ' ~ ' + shortDate(window.to);
  }

  function initHotspot() {
    var panel = document.getElementById('hotspotPanel');
    var list = document.getElementById('hotspotList');
    var tabsHost = document.getElementById('hotspotTabs');
    var meta = document.getElementById('hotspotMeta');
    var button = document.getElementById('hotspotCollect');
    var errorLine = document.getElementById('hotspotError');
    if (!panel || !list || !tabsHost || !meta || !button || !errorLine) return;
    var hasCache = false;
    var items = [];        // 全量条目（客户端过滤的数据源，一次采集只渲染一次 DOM）
    var categories = [];   // 类别清单（接口返回体的 categories，来自客户包词表）
    var active = ALL;      // 当前 TAB：默认「全部」

    function setError(text) {
      if (text) {
        errorLine.textContent = text;
        errorLine.hidden = false;
      } else {
        errorLine.textContent = '';
        errorLine.hidden = true;
      }
    }

    function setBusy(busy) {
      button.disabled = busy;
      button.textContent = busy ? '采集中…' : (hasCache ? '重新采集' : '采集要闻');
    }

    function categoryOf(item) {
      return (item && item.category) || '';
    }

    function countOf(category) {
      var total = 0;
      items.forEach(function (item) { if (categoryOf(item) === category) total += 1; });
      return total;
    }

    function visible() {
      if (active === ALL) return items;
      return items.filter(function (item) { return categoryOf(item) === active; });
    }

    function renderTabs() {
      tabsHost.textContent = '';
      [ALL].concat(categories).forEach(function (category) {
        var count = category === ALL ? items.length : countOf(category);
        var tab = document.createElement('button');
        tab.type = 'button';
        tab.className = 'social-tab hotspot-tab';
        tab.setAttribute('role', 'tab');
        tab.setAttribute('data-category', category);
        tab.setAttribute('aria-selected', category === active ? 'true' : 'false');
        if (category === active) tab.setAttribute('data-state', 'active');
        tab.textContent = category;
        var badge = document.createElement('span');
        badge.className = 'faint tiny';
        badge.textContent = ' (' + count + ')';
        tab.appendChild(badge);
        if (category !== active && count === 0) {
          // 置灰但可点：切过去显示空态「—」
          tab.style.color = 'var(--faint)';
        }
        tab.addEventListener('click', function () {
          if (active === category) return;
          active = category;
          renderTabs();
          renderList();
        });
        tabsHost.appendChild(tab);
        if (category === active && tab.scrollIntoView) {
          // TAB 多时是单行横向滚动：把当前 TAB 滚进可视区，否则切到靠右的类别后看不出选中态
          tab.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        }
      });
    }

    function renderList() {
      list.textContent = '';
      visible().forEach(function (item, index) {
        var li = document.createElement('li');
        li.className = 'hotspot-item';

        var head = document.createElement('div');
        head.className = 'hotspot-line';

        var rank = document.createElement('span');
        rank.className = 'hotspot-rank';
        rank.textContent = (item.rank || index + 1) + '.';

        var link = document.createElement('a');
        link.href = item.url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = item.title;

        var sep = document.createElement('span');
        sep.className = 'hotspot-sep';
        sep.textContent = '｜';

        var category = document.createElement('span');
        category.className = 'hotspot-cat';
        category.textContent = categoryOf(item) || '—';

        head.appendChild(rank);
        head.appendChild(link);
        head.appendChild(sep);
        head.appendChild(category);
        li.appendChild(head);

        if (item.summary) {
          var summary = document.createElement('p');
          summary.className = 'hotspot-summary';
          summary.textContent = item.summary;
          li.appendChild(summary);
        }
        list.appendChild(li);
      });
    }

    function render(body) {
      hasCache = !!body.available && Array.isArray(body.items) && body.items.length > 0;
      var line = windowLabel(body.window);
      if (body.collected_at) line += ' · 采集于 ' + clock(body.collected_at);
      else line += ' · 未采集';
      meta.textContent = line;
      if (body.collected_at) meta.title = '采集时刻 ' + body.collected_at;

      items = Array.isArray(body.items) ? body.items : [];
      categories = Array.isArray(body.categories) ? body.categories : [];
      active = ALL;
      renderTabs();
      renderList();
      setBusy(false);
    }

    function load() {
      setError('');
      fetch('/api/hotspot', { headers: { Accept: 'application/json' } })
        .then(function (response) { return response.json(); })
        .then(render)
        .catch(function (err) { setError('hotspot_load_failed'); });
    }

    button.addEventListener('click', function () {
      setError('');
      setBusy(true);
      fetch('/api/hotspot/collect', { method: 'POST', headers: { Accept: 'application/json' } })
        .then(function (response) {
          return response.json().then(function (body) { return { ok: response.ok, body: body }; });
        })
        .then(function (result) {
          if (!result.ok) {
            // 错误码原样显示（search_not_configured / hotspot_category_invalid / hotspot_model_failed…）
            var detail = result.body && result.body.detail;
            setError(typeof detail === 'string' ? detail : 'hotspot_collect_failed');
            setBusy(false);
            return;
          }
          render(result.body);
        })
        .catch(function () { setError('hotspot_collect_failed'); setBusy(false); });
    });

    load();
  }

  function initSocial() {
    var panel = document.getElementById('socialPanel');
    var body = document.getElementById('socialBody');
    if (!panel || !body) return;
    var tabs = Array.prototype.slice.call(panel.querySelectorAll('[data-platform]'));
    if (!tabs.length) return;

    function activePlatform() {
      var current = panel.querySelector('[data-platform][data-state="active"]');
      return current ? current.getAttribute('data-platform') : tabs[0].getAttribute('data-platform');
    }

    function renderEmpty() {
      body.textContent = '';
      var dash = document.createElement('p');
      dash.className = 'social-empty';
      dash.textContent = '—';
      body.appendChild(dash);
    }

    function render(payload) {
      body.textContent = '';
      var items = (payload && payload.items) || [];
      if (!items.length) { renderEmpty(); return; }
      var list = document.createElement('ol');
      list.className = 'social-list';
      items.forEach(function (item, index) {
        var li = document.createElement('li');
        li.textContent = (item.rank || index + 1) + '. ' + (item.title || '');
        list.appendChild(li);
      });
      body.appendChild(list);
    }

    function load(platform) {
      fetch('/api/social-hotlist?platform=' + encodeURIComponent(platform),
            { headers: { Accept: 'application/json' } })
        .then(function (response) { return response.json(); })
        .then(render)
        .catch(renderEmpty);
    }

    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        // 切换 tab 只换内容区：活跃态从所有 tab 上摘掉，再给当前 tab 打 active
        tabs.forEach(function (other) { other.removeAttribute('data-state'); });
        tab.setAttribute('data-state', 'active');
        load(tab.getAttribute('data-platform'));
      });
    });

    load(activePlatform());
  }

  function boot() { initHotspot(); initSocial(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
