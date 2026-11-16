"""Word 97-2003（`.doc`）读取器：把 dochan 的文档模型映射成 `read_docx` 的 blocks 契约。

为什么不做成 `read_docx` 的分支：
    两种格式在字节层完全不同（OLE2 复合文件 vs OOXML ZIP），`read_docx` 的第一行
    `zipfile.is_zipfile` 就是它对「贴了 OOXML 标签的 ZIP」的承诺。在它内部挂分支等于
    让这个承诺失效，读的人再也无法只凭函数名判断输入形态。派发只在
    `core.tools.template_compare.parse_report_document` 一处发生。

为什么噪声在读取层清：
    `.doc` 的文档属性（SummaryInformation 流）与域代码（bookmark 标记）会被解析器
    当成正文元素吐出来，图片占位符也留在正文里。若留给下游，`compare_reports` 的
    SequenceMatcher 会把这些伪段落算成真实差异，比对结果直接失真。清理属于
    「读这个格式的一部分」，不是业务规则——所以它必须留在本模块，不上升到调用方。

dochan 是可选依赖：未安装时 `read_doc` 抛 `doc_parser_not_installed`，而**导入本模块
不会失败**（`.docx` 链路不因缺少 `.doc` 解析器而挂）。
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

from core.tools.ooxml import UnreadableDocument

LOG = logging.getLogger(__name__)

#: OLE2 复合文件魔数——`.doc` 的容器格式签名。
OLE2_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'

#: 域代码书签标记，如 `[bookmark: OLE_LINK5]`。**不吃尾随空白**：吃了会把 `前\n后` 粘成 `前后`。
BOOKMARK_RE = re.compile(r'\[bookmark:[^\]]*\]')
#: 图片占位符，如 `[이미지: image1.emf]`——它是图形对象的文本替身，不是正文。
IMAGE_PLACEHOLDER_RE = re.compile(r'\[이미지:[^\]]*\]')
#: 两类行内噪声的合并扫描式：一次 `sub` 走完，替换函数拿到的左右邻位置才与原文一致。
INLINE_NOISE_RE = re.compile(f'(?:{BOOKMARK_RE.pattern})|(?:{IMAGE_PLACEHOLDER_RE.pattern})')
#: 中文/西文标点——被它隔开的删除点已经断开，不需要再补空格。
PUNCTUATION = frozenset('，。、；：！？,.;:!?（）()《》〈〉“”"\'‘’·…')
#: 页脚页码行，如 `- 2 -` / `— 12 —` / 全角 `－ 12 －`。
PAGE_FOOTER_RE = re.compile(r'^[-－—–]\s*\d+\s*[-－—–]$')
#: 文档属性退化判据之一：作者行。
AUTHOR_LINE_RE = re.compile(r'^Author\s*[:：]')
#: 文档属性退化判据之二：`短标题+长数字ID`（如 `楠木1420640464`）；第 2 组是数字串。
TITLE_ID_LINE_RE = re.compile(r'^([\u4e00-\u9fffA-Za-z]{1,40})\s*(\d{6,})$')
#: 退化判据的长度上限：文档属性段都很短，超过这个长度就是正文。
METADATA_MAX_CHARS = 24
#: 文档属性段里不会有中文句读；出现句读说明它是正文句子。
CHINESE_PUNCT_RE = re.compile(r'[，。、；：]')


def is_legacy_doc(path: Path) -> bool:
    """按扩展名 + OLE2 魔数**双判**。只认扩展名会把改了后缀的 docx（实为 ZIP）送错分支。"""
    path = Path(path)
    if path.suffix.lower() != '.doc':
        return False
    return _has_ole2_header(path)


def read_doc(path: Path) -> dict:
    """`.doc` → 与 `read_docx` 相同的 `{'path', 'blocks'}` 契约。

    `blocks` 的 `index` 是**清理后的连续序号**（0..n-1），不是原始文档元素位置——
    下游只会把这个序号当「第几块」用，留洞会让它误以为丢了内容。
    """
    path = Path(path)
    if not _has_ole2_header(path):
        raise UnreadableDocument('unreadable_document: not an OLE2 compound file')
    try:
        from dochan import Dochan
        from dochan.model.document import Paragraph
        from dochan.model.table import Table
    except ImportError as exc:  # 可选依赖：没装解析器不等于文档坏了
        raise UnreadableDocument('doc_parser_not_installed') from exc
    try:
        document = Dochan(str(path)).doc
    except Exception as exc:
        raise UnreadableDocument(f'unreadable_document: {exc}') from exc
    errors = list(getattr(document, 'errors', None) or [])
    if errors:  # 解析器报告了可恢复问题：记录，但仍然尝试给出文本
        LOG.warning('doc97: %s parsed with %d recoverable error(s): %s',
                    path.name, len(errors), '; '.join(map(str, errors))[:500])
    blocks = _to_blocks(document, Paragraph, Table)
    if not blocks:
        raise UnreadableDocument('unreadable_document: no readable text')
    return {'path': str(path), 'blocks': blocks}


def _has_ole2_header(path: Path) -> bool:
    try:
        with path.open('rb') as handle:
            return handle.read(len(OLE2_MAGIC)) == OLE2_MAGIC
    except OSError:
        return False


def _provenance_path(element) -> str:
    provenance = getattr(element, 'provenance', None)
    return str(getattr(provenance, 'path', '') or '')


def _from_summary_information(element) -> bool:
    """文档属性流（SummaryInformation）被解析成的元素——它不是正文。"""
    return 'SummaryInformation' in _provenance_path(element)


def _inline_noise_replacement(match: re.Match) -> str:
    """删掉噪声；两侧紧邻的都是文字（非空白、非标点）时补一个空格，否则直接删。

    为什么不是无条件删：占位符/书签是**零宽**的域代码标记，删掉它等于把左右两段
    正文拼在一起——`正文[bookmark: _Toc1]后文` 会变成 `正文后文`（粘词）。补空格只在
    「删了就会粘连」时发生；两侧已有空白或标点断开时补空格反而是多一个空格。
    """
    text = match.string
    left = text[match.start() - 1] if match.start() else ''
    right = text[match.end()] if match.end() < len(text) else ''
    adjacent = left and right and not left.isspace() and not right.isspace()
    if adjacent and left not in PUNCTUATION and right not in PUNCTUATION:
        return ' '
    return ''


def _clean_inline(text: str) -> str:
    """剥掉行内噪声：域代码书签、图片占位符。"""
    if '[' not in text:
        return text
    cleaned = INLINE_NOISE_RE.sub(_inline_noise_replacement, text)
    # 只有真的删过东西才清首尾空白：删除点落在行首/行尾会留下一个空格；没删过就不该
    # strip，那会改到正文的原始形态。
    return cleaned.strip() if cleaned != text else text


def _is_page_footer(text: str) -> bool:
    """页脚页码行——`read_docx` 只读 `w:body`，所以这里也要丢掉。"""
    return bool(PAGE_FOOTER_RE.match(text.strip()))


def _is_calendar_number(digits: str) -> bool:
    """`20260801` / `202608` 这类日历数——它跟在标题后面时是日期，不是内部 ID。"""
    if len(digits) == 6:
        year, month = int(digits[:4]), int(digits[4:])
        return 1900 <= year <= 2100 and 1 <= month <= 12
    if len(digits) == 8:
        year, month, day = int(digits[:4]), int(digits[4:6]), int(digits[6:])
        try:
            date(year, month, day)
        except ValueError:
            return False
        return 1900 <= year <= 2100
    return False


def _looks_like_metadata(text: str) -> bool:
    """退化判据：拿不到 provenance 时，靠文本形态认文档属性段。

    为什么必须收紧：`龙川舆情月报20260801`（标题+日期）与 `楠木1420640464`（人名+内部 ID）
    在形态上完全相同，只看「文字+长数字」会把前者当真属性删掉、丢掉真标题。区分点是
    **数字是不是一个日历数**：日历数属于正文标题，内部 ID 不是。段长上限与中文句读
    再兜一层——属性段都很短，也不会带句读。
    """
    bare = text.strip()
    if AUTHOR_LINE_RE.match(bare):
        return True
    match = TITLE_ID_LINE_RE.match(bare)
    if not match or len(bare) >= METADATA_MAX_CHARS or CHINESE_PUNCT_RE.search(bare):
        return False
    return not _is_calendar_number(match.group(2))


def _clean_paragraph_text(text: str) -> str:
    text = _clean_inline(text)
    return '' if _is_page_footer(text) else text


def _table_rows(element) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in element.rows:
        rows.append(['' if cell.is_merged_away else _clean_inline(cell.text).strip() for cell in row])
    return rows


def _to_blocks(document, paragraph_cls, table_cls) -> list[dict]:
    """遍历段落/表格，剔除噪声后按 blocks 契约重新连续编号。

    只认 `Paragraph` / `Table`：`Image`、`HeaderFooter`、`Equation` 一律跳过——
    `read_docx` 只读 `w:body`，正文之外的图形与页眉页脚不属于这个契约。
    """
    blocks: list[dict] = []
    for section in getattr(document, 'sections', None) or []:
        for element in getattr(section, 'elements', None) or []:
            if isinstance(element, paragraph_cls):
                if _from_summary_information(element):
                    continue
                text = _clean_paragraph_text(element.text)
                if not text.strip():
                    continue
                if not blocks and not _provenance_path(element) and _looks_like_metadata(text):
                    continue
                style = f'Heading{element.heading_level}' if element.heading_level else ''
                blocks.append({'index': len(blocks), 'kind': 'paragraph', 'text': text, 'style': style})
            elif isinstance(element, table_cls):
                rows = _table_rows(element)
                if not rows:
                    continue
                blocks.append({'index': len(blocks), 'kind': 'table', 'rows': rows,
                               'text': ' | '.join(' / '.join(row) for row in rows)})
    return blocks
