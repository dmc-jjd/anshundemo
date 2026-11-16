"""`.doc` 接入模板比对链路后的收口缺陷回归（B1 / W1 / W2 / W3 + N1~N4）。

为什么单开一个文件而不是塞进 `test_doc97.py`：
    `test_doc97.py` 钉的是**读取器本身**（解析契约、噪声清理、派发）。这里钉的是
    **绕过派发点的四个下游**——它们不属于读取器语义，坏掉的方式也不同（500 / 静默 /
    说谎的字段）。两组失败信息的价值不一样，混在一起会让「读取器坏了」和「某个端点
    忘了走派发点」难以区分。

为什么 N1~N3 要对照修复前输出：
    这三条都是**判据收紧**，风险在「改宽了」或「改窄了」。所以每条同时给正例和反例，
    另有一条 `test_sample_blocks_unchanged_by_noise_fixes` 用真样本的文本摘要证明
    「样本 41 块逐字未变」——收紧判据没有碰到真实报告的正文。

样本 `.doc` 不在仓库里（客户原件、只读）：依赖它的用例单独挂 `requires_sample`，
缺样本时只跳这几条，纯单元用例照跑。
"""

from __future__ import annotations

import hashlib
import logging
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import report_parameters
from app.report_parameters import suggestions
from app.schemas import TaskState
from app.storage import Store
from core.charts import spec as chart_spec
from core.tools.doc97 import _clean_inline, _is_page_footer, _looks_like_metadata, read_doc
from core.tools.ooxml import UnreadableDocument
from core.tools.template_compare import parse_report_document

REPO = Path(__file__).resolve().parents[1]
SAMPLE = Path(r'C:\Users\knwl\Desktop\国内研究室报告\月报\龙川月报\龙川县8月舆情月报.doc')
requires_sample = pytest.mark.skipif(not SAMPLE.exists(), reason='样本 .doc 不在本机')

#: 修复 N1~N3 前实测的样本文本摘要（41 块、逐字拼接）。它是「判据收紧没碰正文」的锁。
SAMPLE_TEXT_DIGEST = '113f4a49329ca606e01e186f6cafd33bc396f257ed4044301ac471826efe3fcd'
SAMPLE_BLOCK_COUNT = 41


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _template_artifact(store: Store, sources: list[Path], task_id: str = 't') -> str:
    """造一个「来源报告 = sources」的确认模板工件；`charts` 非空让 chart_spec 不必真读版式。"""
    return store.put_artifact(task_id, 'template_version', {
        'source_reports': [{'path': str(path), 'sha256': _sha(path)} for path in sources],
        'charts': [{'id': 'sentiment', 'drawing_index': 1, 'title': '舆情调性分布', 'style': 'pie',
                    'style_basis': '用户确认的月报图形规则，可在模板审核时更换',
                    'scope': 'all_records', 'unit': '条'}],
    })


def _client(tmp_path, monkeypatch, sources: list[Path]) -> TestClient:
    store = Store(tmp_path / 'store')
    ref = _template_artifact(store, sources)
    store.put_task(TaskState(id='t', kind='template', phase='awaiting_review',
                             metadata={'confirmed_template_ref': ref}))
    monkeypatch.setattr(main, 'store', store)
    return TestClient(main.app)


# --------------------------------------------------------------- B1：sources 端点

@requires_sample
def test_template_sources_endpoint_reads_legacy_doc(tmp_path, monkeypatch):
    """`GET /api/templates/{id}/sources` 含 `.doc` 源 → 200，且该源 blocks 读得出来。

    修复前这里直接 `read_docx`，`.doc` 落到 `not an unencrypted OOXML ZIP` → 500，
    前端「N 份来源报告」页签（`app/static/app.js`）一点开就崩。
    """
    from test_structured_template import docx

    mixed = tmp_path / 'also.docx'
    docx(mixed, '2026年第8期 安顺市2026年8月网络舆情分析报告')
    with _client(tmp_path, monkeypatch, [SAMPLE, mixed]) as client:
        response = client.get('/api/templates/t/sources')

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item['name'] for item in body] == [SAMPLE.name, mixed.name]
    assert body[0]['blocks'], '.doc 源的 blocks 不能为空'
    assert body[0]['blocks'][0]['text'] == '舆 情 月 报'
    assert body[1]['blocks'][0]['text'] == '2026年第8期 安顺市2026年8月网络舆情分析报告'


# --------------------------------------------------------------- W1：图表原图端点

@requires_sample
def test_chart_source_for_legacy_doc_is_404_not_500(tmp_path, monkeypatch):
    """`.doc` 内嵌的是 OLE2 里的 EMF，不是 ZIP 里的 media——按「不可预览」404，不是 500。"""
    with _client(tmp_path, monkeypatch, [SAMPLE]) as client:
        response = client.get('/api/templates/t/charts/sentiment/source')

    assert response.status_code == 404, response.text
    assert response.json()['detail'] == 'source_chart_unavailable'


def test_chart_source_for_broken_docx_is_404_not_500(tmp_path, monkeypatch):
    """坏 `.docx`（后缀对、内容不是 ZIP）：`BadZipFile` 必须落在同一个 404 分支里。"""
    broken = tmp_path / 'broken.docx'
    broken.write_bytes(b'PK\x03\x04 truncated, not a real zip')
    with _client(tmp_path, monkeypatch, [broken]) as client:
        response = client.get('/api/templates/t/charts/sentiment/source')

    assert response.status_code == 404, response.text
    assert response.json()['detail'] == 'source_chart_unavailable'


@requires_sample
def test_source_image_rejects_legacy_doc_before_zip_read(tmp_path):
    """直接调实现层：`BadZipFile` 不能漏出来（它不是 ValueError，路由层兜不住）。"""
    template = {'source_reports': [{'path': str(SAMPLE), 'sha256': _sha(SAMPLE)}],
                'charts': [{'id': 'sentiment'}]}
    with pytest.raises(ValueError, match='source_chart_unavailable'):
        chart_spec.source_image(template, 'sentiment', 0, data_root=tmp_path)


# --------------------------------------------------------------- W2：上传响应 readable

@requires_sample
def test_upload_legacy_doc_reports_readable(tmp_path, monkeypatch):
    """合法 `.doc` 完全可读——`readable=false` 是谎报，会让前端把可用文件当坏文件。"""
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    monkeypatch.setattr(main, 'UPLOADS', uploads)
    with TestClient(main.app) as client:
        response = client.post('/api/files', files={
            'file': (SAMPLE.name, SAMPLE.read_bytes(), 'application/msword')})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body['readable'] is True
    assert body['reason'] is None, '可读的 .doc 不该带 not_unencrypted_ooxml'


def test_upload_unreadable_reason_follows_format(tmp_path, monkeypatch):
    """读不了时文案要指向用户能做的动作：`.doc` 后缀说「认不出」，`.docx` 说不是 OOXML。"""
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    monkeypatch.setattr(main, 'UPLOADS', uploads)
    with TestClient(main.app) as client:
        legacy = client.post('/api/files', files={'file': ('bad.doc', b'definitely not ole2')})
        modern = client.post('/api/files', files={'file': ('bad.docx', b'definitely not a zip')})

    assert legacy.status_code == modern.status_code == 200
    assert legacy.json()['readable'] is False
    assert legacy.json()['reason'] == 'legacy_doc_unreadable'
    assert modern.json()['readable'] is False
    assert modern.json()['reason'] == 'not_unencrypted_ooxml'


# --------------------------------------------------------------- W3：期号推断

@requires_sample
def test_suggestions_routes_doc_source_through_dispatcher(tmp_path, monkeypatch, caplog):
    """含 `.doc` 源的模板必须走 `parse_report_document`，否则 `.doc` 对期号推断贡献恒为零。"""
    calls = []
    real = parse_report_document

    def spy(path):
        calls.append(Path(path))
        return real(path)

    monkeypatch.setattr(report_parameters, 'parse_report_document', spy)
    with caplog.at_level(logging.WARNING, logger='app.report_parameters'):
        result = suggestions({'source_reports': [{'path': str(SAMPLE)}]}, '2026-08')

    assert calls == [SAMPLE], '源报告没经派发点读取'
    assert not [r for r in caplog.records if '源报告读取失败' in r.getMessage()]
    assert result['samples'] == [] and result['issue_number'] is None  # 样本正文没有报告标题句，推断为空的正确结果


def test_issue_is_inferred_from_legacy_source_blocks(tmp_path, monkeypatch):
    """`.doc` 的 blocks 真的进了期号正则：样本正文缺「…网络舆情分析报告」标题句，
    故用 `.doc` 契约形状的 blocks 作替身，证明这条链路对期号是有产出的。"""
    blocks = [{'index': 0, 'kind': 'paragraph', 'text': '（2026年 第3期）', 'style': ''},
              {'index': 1, 'kind': 'paragraph', 'text': '龙川县2026年8月网络舆情分析报告', 'style': ''}]
    monkeypatch.setattr(report_parameters, 'parse_report_document',
                        lambda path: {'path': str(path), 'blocks': blocks})
    result = suggestions({'source_reports': [{'path': str(tmp_path / 'legacy.doc')}]}, '2026-08')

    assert result['samples'] == [{'year': 2026, 'month': 8, 'issue_number': 3}]
    assert result['issue_number'] == 3


def test_unreadable_source_warns_instead_of_silence(tmp_path, caplog):
    """读不了也必须留痕：文件名 + 异常类型。静默少一份证据会让期号推断无声变差。"""
    broken = tmp_path / 'broken.docx'
    broken.write_bytes(b'not a zip at all')
    with caplog.at_level(logging.WARNING, logger='app.report_parameters'):
        result = suggestions({'source_reports': [{'path': str(broken)}]}, '2026-08')

    warnings = [r for r in caplog.records if '源报告读取失败' in r.getMessage()]
    assert len(warnings) == 1
    assert warnings[0].levelno == logging.WARNING
    message = warnings[0].getMessage()
    assert 'broken.docx' in message and 'UnreadableDocument' in message
    assert result['samples'] == []


# --------------------------------------------------------------- N1：行内噪声不粘词

def test_inline_noise_removal_keeps_words_apart():
    """删除点两侧都是文字 → 补一个空格；修复前是直接删，两段正文粘成一个词。"""
    assert _clean_inline('前[이미지: a.emf]\n后') == '前\n后'   # 修复前：'前后'（`\\s*` 吃掉换行）
    assert _clean_inline('正文[bookmark: _Toc1]后文') == '正文 后文'  # 修复前：'正文后文'


def test_inline_noise_removal_does_not_add_double_space():
    """两侧已经有空白或标点断开时不补空格；行首行尾的空白仍清掉。"""
    assert _clean_inline('[bookmark: OLE_LINK5] 图1：态势图') == '图1：态势图'
    assert _clean_inline('前[이미지: x.emf]，后') == '前，后'
    assert _clean_inline('[이미지: x.emf]') == ''


# --------------------------------------------------------------- N2：全角页脚

def test_page_footer_accepts_fullwidth_and_halfwidth_dashes():
    assert _is_page_footer('－ 12 －')   # 修复前：False（全角漏判）
    assert _is_page_footer('－12－')     # 修复前：False
    assert _is_page_footer('- 12 –')
    assert _is_page_footer('  — 12 — ')
    assert not _is_page_footer('－ 12 期')
    assert not _is_page_footer('图2：来源分布图')


# --------------------------------------------------------------- N3：文档属性判据

def test_metadata_heuristic_keeps_title_with_calendar_date():
    """标题+日期是真标题，必须保留；标题+内部 ID 才是文档属性。"""
    assert _looks_like_metadata('龙川舆情月报20260801') is False   # 修复前：True（真标题被删）
    assert _looks_like_metadata('龙川舆情月报202608') is False
    assert _looks_like_metadata('楠木1420640464') is True


def test_metadata_heuristic_length_and_punctuation_guards():
    assert _looks_like_metadata('龙川舆情月报20260801，本期发布') is False   # 带句读 → 正文
    long_title = '一二三四五六七八九十一二三四五六七八' + '1420640464'
    assert len(long_title) >= 24
    assert _looks_like_metadata(long_title) is False                    # 超长 → 正文
    assert _looks_like_metadata('Author: 铃铭') is True


# --------------------------------------------------------------- N4：反向伪装

@requires_sample
def test_renamed_legacy_doc_gets_actionable_message(tmp_path):
    """真 `.doc` 手动改名 `.docx`：报错要能指导「把扩展名改回 .doc」，而不是 OOXML 术语。"""
    renamed = tmp_path / 'real.docx'
    renamed.write_bytes(SAMPLE.read_bytes())
    with pytest.raises(UnreadableDocument) as caught:
        parse_report_document(str(renamed))

    message = str(caught.value)
    assert message.startswith('unreadable_document:')
    assert '.doc' in message and '扩展名' in message


def test_broken_docx_is_not_mistaken_for_renamed_legacy_doc(tmp_path):
    """补救判定不能误伤：真坏 `.docx` 仍报原来的 OOXML 文案。"""
    broken = tmp_path / 'broken.docx'
    broken.write_bytes(b'not a zip at all')
    with pytest.raises(UnreadableDocument) as caught:
        parse_report_document(str(broken))
    assert 'not an unencrypted OOXML ZIP' in str(caught.value)


# --------------------------------------------------------------- 样本回归锁

@requires_sample
def test_sample_blocks_unchanged_by_noise_fixes():
    """N1~N3 是判据收紧：真实样本的 41 块必须逐字不变（页脚/属性段在样本上是休眠路径）。"""
    blocks = read_doc(SAMPLE)['blocks']
    assert len(blocks) == SAMPLE_BLOCK_COUNT
    digest = hashlib.sha256('\n'.join(block['text'] for block in blocks).encode()).hexdigest()
    assert digest == SAMPLE_TEXT_DIGEST, '样本正文被噪声清理改动——收紧判据碰到了真实内容'
