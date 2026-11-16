"""`.doc`（Word 97-2003）读取链路的测试。

为什么集成用例对**真实样本**跑而不是构造假 `.doc`：
    OLE2 复合文件的解析正确性只有真文件能证明——手搓的假尺寸/假片段要么被解析器
    直接拒绝，要么只走到错误路径。样本不在仓库里（客户原件，只读），所以每个
    集成用例单独挂 `requires_sample`，缺样本时只跳这几条。

为什么不用模块级 `pytestmark`：
    本文件同时含不依赖样本的纯单元用例（噪声正则、OLE2 双判）。模块级 skip 会把
    它们一起跳过，于是「没样本的机器上等于没测」——这正是要避免的形态。

断言里的具体数字（1659→1700）来自样本本体，不是猜的。
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path

import pytest

from core.tools.doc97 import (_clean_inline, _is_page_footer, _looks_like_metadata,
                              is_legacy_doc, read_doc)
from core.tools.ooxml import UnreadableDocument
from core.tools.template_compare import compare_reports, parse_report_document

REPO = Path(__file__).resolve().parents[1]
SAMPLE = Path(r'C:\Users\knwl\Desktop\国内研究室报告\月报\龙川月报\龙川县8月舆情月报.doc')
TEMPLATE = REPO / 'templates' / 'anshun_monthly' / 'template-with-placeholders.docx'

requires_sample = pytest.mark.skipif(not SAMPLE.exists(), reason='样本 .doc 不在本机')
FOOTER_RE = re.compile(r'^[-—–]\s*\d+\s*[-—–]$')


@pytest.fixture(scope='module')
def parsed() -> dict:
    return read_doc(SAMPLE)


# ---------------------------------------------------------------- 集成（需样本）

@requires_sample
def test_read_doc_returns_docx_blocks_contract(parsed: dict) -> None:
    assert Path(parsed['path']) == SAMPLE
    blocks = parsed['blocks']
    assert len(blocks) > 20
    assert {b['kind'] for b in blocks} <= {'paragraph', 'table'}
    assert {'paragraph', 'table'} == {b['kind'] for b in blocks}
    for block in blocks:
        assert block['text'].strip()
        if block['kind'] == 'paragraph':
            assert set(block) >= {'index', 'kind', 'text', 'style'}
        else:
            assert block['rows']
            assert all(isinstance(row, list) for row in block['rows'])


@requires_sample
def test_noise_is_cleaned_inside_read_doc(parsed: dict) -> None:
    for block in parsed['blocks']:
        text = block['text']
        assert '[bookmark:' not in text
        assert '이미지' not in text
        assert not text.strip().startswith('Author:')
        assert not any(FOOTER_RE.match(line.strip()) for line in text.splitlines())


@requires_sample
def test_index_is_contiguous(parsed: dict) -> None:
    assert [b['index'] for b in parsed['blocks']] == list(range(len(parsed['blocks'])))


@requires_sample
def test_is_legacy_doc_dual_checks_suffix_and_magic() -> None:
    assert is_legacy_doc(SAMPLE) is True
    assert is_legacy_doc(TEMPLATE) is False


@requires_sample
def test_parse_report_document_dispatches_to_doc_reader(parsed: dict) -> None:
    document = parse_report_document(str(SAMPLE))
    assert document['blocks'] == parsed['blocks']
    assert document['sha256'] == hashlib.sha256(SAMPLE.read_bytes()).hexdigest()


@requires_sample
def test_compare_reports_runs_on_sample(parsed: dict) -> None:
    base = dict(parsed, sha256=hashlib.sha256(SAMPLE.read_bytes()).hexdigest())
    other = {'path': 'modified.doc', 'sha256': 'f' * 64,
             'blocks': [dict(block) for block in parsed['blocks']]}
    edited = False
    for block in other['blocks']:
        if block['kind'] == 'paragraph' and '1659' in block['text']:
            block['text'] = block['text'].replace('1659', '1700', 1)
            edited = True
            break
    assert edited, '样本正文里没有 1659——断言值取自该样本实测，找不到说明样本被换掉了'

    result = compare_reports([base, other])
    assert result['occurrences']
    changed = [a for a in result['alignments'] if a['type'] != 'equal']
    assert changed
    assert any('1700' in text for item in changed for text in item['other_text'])
    assert any('1659' in text for item in changed for text in item['base_text'])


# ---------------------------------------------------------------- 单元（不要样本）

def test_clean_inline_strips_bookmark_prefix() -> None:
    assert _clean_inline('[bookmark: OLE_LINK5] 图1：态势图') == '图1：态势图'
    # N1：删除点两侧都是文字且无空白/标点隔开 → 补一个空格，否则两段正文粘成一个词。
    assert _clean_inline('正文[bookmark: _Toc1]后文') == '正文 后文'
    assert _clean_inline('无噪声正文') == '无噪声正文'


def test_clean_inline_strips_image_placeholder() -> None:
    # N1：同一规则作用于图片占位符；原实现里 `\s*` 还会吃掉后面的换行，把两段并成一行。
    assert _clean_inline('前[이미지: image1.emf]后') == '前 后'
    assert _clean_inline('[이미지: image2.emf]') == ''


def test_page_footer_detection() -> None:
    assert _is_page_footer('- 2 -')
    assert _is_page_footer('  — 12 — ')
    assert not _is_page_footer('2026年9月5日')
    assert not _is_page_footer('第2页')
    assert not _is_page_footer('图2：来源分布图')


def test_metadata_heuristic_matches_document_properties() -> None:
    assert _looks_like_metadata('Author: 铃铭\ue14c')
    assert _looks_like_metadata('楠木1420640464')
    assert not _looks_like_metadata('舆 情 月 报')
    assert not _looks_like_metadata('（2026年 第3期）')
    assert not _looks_like_metadata('一、舆情特点')


def test_read_doc_rejects_non_ole2_file(tmp_path: Path) -> None:
    fake = tmp_path / 'renamed.doc'
    fake.write_bytes(b'PK\x03\x04 not an OLE2 compound file')
    with pytest.raises(UnreadableDocument, match='not an OLE2 compound file'):
        read_doc(fake)


def test_is_legacy_doc_rejects_renamed_docx(tmp_path: Path) -> None:
    fake = tmp_path / 'actually-a-zip.doc'
    with zipfile.ZipFile(fake, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document/>')
    assert fake.read_bytes()[:2] == b'PK'
    assert is_legacy_doc(fake) is False
    assert is_legacy_doc(tmp_path / 'plain.docx') is False
