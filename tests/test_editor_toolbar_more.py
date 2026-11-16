# -*- coding: utf-8 -*-
"""05 报告撰写页工具栏「更多」菜单的结构回归。

背景：加上 240px 左栏后右栏只剩 ~1200px，.ed-bar 的 flex-wrap 会把工具栏折成
两行、把「保存到系统」挤到第二行。修法是把 6 个低频命令收进最右侧「更多」菜单，
工具栏回到一行。这里钉住「收拢后的结构契约」——不改任何视觉断言（那些由
.conda/uiwork/accept_toolbar.py 的 headless 实跑负责），只防结构被改回去。
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / 'app' / 'static' / 'final-editor.html'
JS = ROOT / 'app' / 'static' / 'final-editor.js'

# 收拢后仍留在工具栏（一行内）的 17 个命令，顺序即渲染顺序。
KEPT = [
    '撤销', '重做', 'B', 'I', 'U', 'S', 'A−', 'A+',
    '左', '中', '右', '两端', 'H1', 'H2', '正文',
    '保存到系统', '导出 docx',
]
# 收进「更多」的 6 个命令：(菜单文字, 定位用的 data 契约)
MENU = [
    ('列表', 'data-list="ul"'),
    ('列表', 'data-list="ol"'),
    ('插表格', 'data-table="1"'),
    ('载入模板', 'id="edLoadTpl"'),
    ('载入报告', 'id="edLoadDoc"'),
    ('打印', 'data-cmd="executePrint"'),
]


class Bar(HTMLParser):
    """收集 .ed-bar 的直接子元素（按出现顺序）与菜单项。"""

    def __init__(self):
        super().__init__()
        self.stack = []
        self.bar_depth = None
        self.panel_depth = None
        self.bar_buttons = []       # 工具栏直系 .ed-btn 的可见文字
        self.panel_items = []       # .ed-mi 的 (文字, 起手标签文本)
        self.panel_attrs = []       # 6 个菜单项的标签原文
        self.has_panel = False
        self.has_more_btn = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get('class') or '').split()
        depth = len(self.stack)
        if self.bar_depth is None and 'ed-bar' in cls:
            self.bar_depth = depth
        elif self.bar_depth is not None and self.panel_depth is None and 'ed-more' in cls:
            self.panel_depth = depth
            self.has_panel = True
        if self.bar_depth is not None and depth == self.bar_depth + 1 and 'ed-btn' in cls:
            self.bar_buttons.append(a.get('id') or '')
            if a.get('id') == 'edMoreBtn':
                self.has_more_btn = True
        if self.panel_depth is not None and 'ed-mi' in cls:
            self.panel_items.append(a.get('aria-label') or a.get('title') or '')
        if tag not in ('br', 'img', 'meta', 'link', 'input', 'hr', 'source', 'path',
                       'circle', 'rect', 'text', 'area', 'base', 'col', 'embed',
                       'param', 'track', 'wbr'):
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
            depth = len(self.stack)
            if self.panel_depth is not None and depth == self.panel_depth:
                self.panel_depth = None
            if self.bar_depth is not None and depth == self.bar_depth:
                self.bar_depth = None


def _bar_html() -> str:
    text = HTML.read_text(encoding='utf-8')
    start = text.index('<div class="ed-bar">')
    end = text.index('<div class="ed-main">', start)
    return text[start:end]


def test_files_are_lf_utf8():
    for path in (HTML, JS):
        data = path.read_bytes()
        assert b'\r' not in data, f'{path.name} 必须是 LF'
        data.decode('utf-8')


def test_toolbar_keeps_17_buttons_plus_more():
    bar = Bar()
    bar.feed(HTML.read_text(encoding='utf-8'))
    assert bar.has_panel and bar.has_more_btn
    # 工具栏直系 .ed-btn = 17 个保留命令 + 更多（菜单项是 .ed-mi，不在其中）
    assert len(bar.bar_buttons) == 18, bar.bar_buttons
    assert bar.bar_buttons[-1] == 'edMoreBtn'


def test_kept_buttons_render_in_order():
    bar_html = _bar_html()
    # 菜单之外的部分：把 .ed-more 面板切掉再比对文字顺序
    head = bar_html.split('<div class="ed-more"')[0]
    buttons = re.findall(r'<button\b[^>]*>(.*?)</button>', head, re.S)
    labels = [re.sub(r'<[^>]+>', '', body).strip() for body in buttons]
    assert labels[-1] == '更多', labels
    assert labels[:-1] == KEPT, labels


def test_six_low_frequency_commands_live_in_menu():
    bar = Bar()
    bar.feed(HTML.read_text(encoding='utf-8'))
    assert len(bar.panel_items) == 6, bar.panel_items
    assert bar.panel_items == ['无序列表', '有序列表', '插入 3×3 表格',
                               '载入模板 docx', '载入已生成报告 docx', '打印']
    bar_html = _bar_html()
    panel = bar_html.split('<div class="ed-more"')[1]
    for _, marker in MENU:
        assert marker in panel, marker
        assert marker not in bar_html.split('<div class="ed-more"')[0], marker


def test_menu_panel_css_contract():
    text = HTML.read_text(encoding='utf-8')
    css = text[text.index('<style>'):text.index('</style>')]
    assert '.ed-more{position:absolute' in css
    assert 'width:168px' in css and 'border-radius:10px' in css
    assert 'box-shadow:var(--shadow)' in css
    assert '.ed-bar.more-open .ed-more{display:block}' in css
    assert '.ed-mi{' in css and 'height:34px' in css and 'padding:0 10px' in css
    assert '.ed-mi.on{background:var(--brand-bg)' in css
    assert '.ed-more-btn[aria-expanded="true"]{background:var(--field)}' in css
    assert '.ed-more-btn[aria-expanded="true"] .ed-caret{transform:rotate(180deg)}' in css
    assert '.ed-msep{height:1px;background:var(--line);margin:4px 0}' in css
    # 点击区不得低于 28px（工具栏整体仍须单行）
    assert 'height:28px;min-height:28px;min-width:28px' in css


def test_js_delegation_and_close_paths():
    js = JS.read_text(encoding='utf-8')
    assert "closest('.ed-btn, .ed-mi')" in js
    assert "btn.id === 'edMoreBtn'" in js
    assert 'function toggleMore()' in js
    assert "classList.add('more-open')" in js and "classList.remove('more-open')" in js
    assert "setAttribute('aria-expanded', 'true')" in js
    assert "event.key !== 'Escape'" in js
    # 点面板外关闭走捕获阶段（画布会吃掉冒泡）
    assert '}, true);' in js
    # 菜单项执行完关闭
    assert 'if (isItem) closeMore();' in js


def test_pressed_state_reuses_range_style_sync():
    js = JS.read_text(encoding='utf-8')
    # 菜单项沿用 .on + aria-pressed，由既有 rangeStyleChange 驱动（不另起一份状态）
    assert "listUl: barEl.querySelector('[data-list=\"ul\"]')" in js
    assert "listOl: barEl.querySelector('[data-list=\"ol\"]')" in js
    assert "btn.classList.add('on')" in js
    assert "btn.setAttribute('aria-pressed', on ? 'true' : 'false')" in js
