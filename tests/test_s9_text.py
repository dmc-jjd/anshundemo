"""S9-A 文本归一化第一批（纯噪声清理）：规则与「下游只读 normalized_*」的证据级验收。

三条界线，本文件逐条守住：
    ① `core/text.py` 是唯一实现——下游不许各写一套正则；
    ② 第一批只删确定不含语义的字符/串，任何"改语义"的动作都不在这里出现
       （数字串 `1000000` 一个 0 都不许少）；
    ③ 下游读的是 `normalized_*`，但历史 artifact 没有该字段时仍要能跑（fallback）。

V2 的判别方式：构造一对记录，让「读原始字段」与「读归一化字段」得到**不同**的合并结果，
再断言实际结果等于后者。只断言"没崩"不算证据。
"""

from __future__ import annotations

import pytest

from app.storage import Store
from app.tool_executor import RunContext
from core.text import NORMALIZATION_VERSION, TOKENIZER_VERSION, normalize_record, normalize_text, norm_or_raw
from core.tools._shared import words
from core.tools.dedup import group_by_representative
from core.tools.records import import_records
from core.tools import events as events_module
from test_s2_manifest_vocabulary import _CaptureStore, _xlsx


# --------------------------------------------------------------------------- #
# V1 归一化规则
# --------------------------------------------------------------------------- #

def test_fullwidth_letters_and_digits_survive_nfkc():
    """全角 `２０２６` → `2026`。

    旧断言钉的是**缺陷本身**：分词器不做 NFKC，全角数字连 token 都不产生
    （`words('２０２６') == set()`）。第二批把 `words()` 接到 `core.text.tokenize`，
    分词入口内先归一化，于是原始全角串已直接得到 `{'2026'}`——缺陷消失，断言翻面。
    """
    assert normalize_text('２０２６年１０月') == '2026年10月'
    assert words('２０２６') == {'2026'}
    assert words(normalize_text('２０２６')) == {'2026'}
    assert words('２０２６') == words('2026')


def test_fullwidth_ascii_letters_become_halfwidth():
    assert normalize_text('ＡＢＣ报告') == 'ABC报告'


def test_hashtag_marks_are_stripped_and_body_kept():
    assert normalize_text('#防汛演练# 今晚开始') == '防汛演练 今晚开始'


def test_mention_is_removed():
    """`@平台名` 里的地名会成为向量实词，属于结构性污染。"""
    assert normalize_text('@平安抚顺 回复了：已处理') == '回复了:已处理'


def test_url_and_shortlink_are_removed():
    assert normalize_text('通报详见 https://t.cn/abc123 原文') == '通报详见 原文'
    assert normalize_text('转发 t.cn/xyz789 查看') == '转发 查看'
    assert normalize_text('来源 v.douyin.com/abc') == '来源'
    assert normalize_text('https://example.com/a?b=1') == ''


def test_platform_watermark_and_bracket_noise_are_removed():
    assert normalize_text('抖音号：abc123 现场视频') == '现场视频'
    assert normalize_text('微博ID xyz 通报全文') == '通报全文'
    assert normalize_text('[展开] 正文内容') == '正文内容'
    assert normalize_text('正文内容 【全文】') == '正文内容'


def test_chinese_repeat_compression_only_from_three():
    """3 个以上才压；2 个是独立的词，压了就是改语义。"""
    assert normalize_text('哈哈哈哈') == '哈'
    assert normalize_text('好好好好好') == '好'
    assert normalize_text('天天') == '天天'
    assert normalize_text('谢谢') == '谢谢'
    assert normalize_text('哈哈哈天天') == '哈天天'


def test_punctuation_repeat_compression():
    assert normalize_text('走了！！！') == '走了!'
    assert normalize_text('等等，，，马上') == '等等,马上'
    assert normalize_text('真的？？') == '真的??'


def test_digit_runs_are_never_compressed():
    """第一批硬边界：数字串的重复 0 是有语义的，压掉就是改数据。"""
    assert normalize_text('1000000') == '1000000'
    assert normalize_text('赔付 1000000 元') == '赔付 1000000 元'
    assert normalize_text('2026-11-13') == '2026-11-13'


def test_batch_two_items_are_not_implemented_yet():
    """繁简、中文数字、百分比、单位——第一批与第二批都不做，这里钉住"没做"。

    第二批只做了两项：jieba 分词与平台模板前缀剥离（见 `tests/test_s10_text.py`）。
    """
    assert normalize_text('三人同行') == '三人同行'
    assert normalize_text('百分之五十') == '百分之五十'
    assert normalize_text('五公里') == '五公里'
    # 繁简转换：`後` 不许变 `后`（第二批才谈）
    assert normalize_text('後續通報') == '後續通報'


def test_zero_width_characters_no_longer_split_chinese_words():
    """零宽字符会把一个词在多字节层面切断，导致分词器看不见这个词。"""
    assert normalize_text('安\u200b顺') == '安顺'
    assert normalize_text('防\u200d汛\ufeff演练') == '防汛演练'
    assert normalize_text('Ａ\u2060Ｂ') == 'AB'


def test_fullwidth_space_and_nbsp_become_single_space():
    assert normalize_text('演练\u3000开始') == '演练 开始'
    assert normalize_text('演练\u00a0开始') == '演练 开始'


def test_whitespace_collapses_and_trims():
    assert normalize_text('  演练 \n\n 开始\t\t完毕  ') == '演练 开始 完毕'


@pytest.mark.parametrize('value', [None, '', '   ', '\u200b\u3000\u00a0'])
def test_empty_and_none_inputs_do_not_raise(value):
    assert normalize_text(value) == ''


def test_normalization_is_idempotent():
    sample = '＠提及 @提及 https://t.cn/a 抖音号:x #话题# 哈哈哈哈！！！　尾巴\u200b'
    once = normalize_text(sample)
    assert normalize_text(once) == once


def test_normalize_record_keeps_original_fields():
    record = {'id': 'r1', 'title': '２０２６ @账号', 'summary': '原文摘要\u200b'}
    out = normalize_record(record)
    assert out['title'] == '２０２６ @账号' and out['summary'] == '原文摘要\u200b'
    assert out['normalized_title'] == '2026'
    assert out['normalized_summary'] == '原文摘要'
    # 副本语义：不改调用方那份。
    assert 'normalized_title' not in record


def test_normalize_record_tolerates_missing_fields():
    out = normalize_record({'id': 'r1'})
    assert out['normalized_title'] == '' and out['normalized_summary'] == ''


# --------------------------------------------------------------------------- #
# V2 下游确实读的是归一化字段（判别式证据）
# --------------------------------------------------------------------------- #

def _pair(raw_title_b, normalized_title_b):
    """a 是"干净"记录；b 的原始标题完全不同，只靠归一化字段与 a 相同。"""
    a = {'id': 'a', 'title': '防汛演练', 'summary': ''}
    b = {'id': 'b', 'title': raw_title_b, 'summary': '',
         'normalized_title': normalized_title_b, 'normalized_summary': ''}
    return a, b


def test_dedup_reads_normalized_title():
    a, b = _pair('夜市烧烤推荐', '防汛演练')
    merged = group_by_representative([a, b], .65)
    assert [g['member_ids'] for g in merged['groups']] == [['a', 'b']]
    # 同一对记录去掉归一化字段 → 两个组。差异只来自"读了哪个字段"。
    raw_only = group_by_representative([a, {'id': 'b', 'title': '夜市烧烤推荐', 'summary': ''}], .65)
    assert [g['member_ids'] for g in raw_only['groups']] == [['a'], ['b']]


def test_dedup_falls_back_to_raw_fields_for_historical_artifacts():
    """历史 artifact 没有 normalized_* 字段，必须仍能跑。"""
    a = {'id': 'a', 'title': '防汛演练', 'summary': ''}
    b = {'id': 'b', 'title': '防汛演练', 'summary': ''}
    assert [g['member_ids'] for g in group_by_representative([a, b], .65)['groups']] == [['a', 'b']]


def test_norm_or_raw_distinguishes_absent_from_empty():
    """字段缺席才回退原文；字段存在但为空就是空——`or` 会把两者混为一谈。"""
    assert norm_or_raw({'title': '@账号 #话题#'}, 'normalized_title', 'title') == '@账号 #话题#'
    assert norm_or_raw({'title': '@账号', 'normalized_title': ''}, 'normalized_title', 'title') == ''
    assert norm_or_raw({'normalized_title': '演练'}, 'normalized_title', 'title') == '演练'
    # 记录连原文都没有时不许抛 KeyError。
    assert norm_or_raw({}, 'normalized_title', 'title') == ''


def test_dedup_does_not_resurrect_raw_text_when_normalized_title_is_empty():
    """纯 `@提及` 记录归一化后标题为空 → 不许把纯噪声原文捞回分词。

    判别式：若 fallback 了，两条 `@同一个账号` 的原文会因共享 `账号` 而并成一组；
    正确语义下它们分词为空、各自独立成组。

    历史 artifact 半段的旧期望是「两条 `@测试账号` 回退原文后**必须合并**」——该期望在
    第二批失效：`tokenize()` 入口内也做归一化，回退到的原文同样会被清成空 token 集，
    于是两边都是零向量、不合并。`norm_or_raw` 的职责是**让历史 artifact 跑得动**
    （不抛错、记录不丢），不是让噪声复活；判据据此改成"能跑 + 两条都在"。
    """
    noisy = [
        {'id': 'n1', 'title': '@测试账号', 'summary': '', 'normalized_title': '', 'normalized_summary': ''},
        {'id': 'n2', 'title': '@测试账号', 'summary': '', 'normalized_title': '', 'normalized_summary': ''},
    ]
    assert [g['member_ids'] for g in group_by_representative(noisy, .65)['groups']] == [['n1'], ['n2']]
    # 同样两条记录删掉归一化字段（历史 artifact）→ 必须回退原文、不抛错、两条都在册。
    historical = [{'id': 'n1', 'title': '@测试账号', 'summary': ''},
                  {'id': 'n2', 'title': '@测试账号', 'summary': ''}]
    result = group_by_representative(historical, .65)
    assert result['all_record_ids'] == ['n1', 'n2']
    assert sorted(rid for g in result['groups'] for rid in g['member_ids']) == ['n1', 'n2']
    # 两条都不含可分词内容（@提及被入口清掉）→ 各自独立，不会因共享 `账号` 伪造合并。
    assert [g['member_ids'] for g in result['groups']] == [['n1'], ['n2']]


def test_dedup_method_records_normalization_version():
    """产物必须自证「哪版归一化 + 哪版分词器切出来的」。

    两个版本号独立演进，别混成一个：规则(归一化) 与 切法(分词器) 可以分别变，
    任何一边变了，旧 artifact 的 token 集都要能归因。
    """
    result = group_by_representative([{'id': 'a', 'title': '防汛演练', 'summary': ''}], .65)
    assert result['method']['normalization'] == NORMALIZATION_VERSION == 'v2'
    assert result['method']['tokenizer'] == TOKENIZER_VERSION


def test_keyword_candidates_tokenize_normalized_title(tmp_path):
    """events.py:19 —— 关键词候选的分词输入必须是 normalized_title。"""
    ctx = RunContext(Store(tmp_path / 'data'), 's9a')
    normalized = [
        {'id': 'r1', 'title': '防汛演练', 'summary': '',
         'normalized_title': '防汛演练', 'normalized_summary': ''},
        {'id': 'r2', 'title': '@测试账号 防汛演练', 'summary': '',
         'normalized_title': '防汛演练', 'normalized_summary': ''},
    ]
    ref = ctx.store.put_artifact('s9a', 'records', {'records': normalized})
    groups = ctx.store.get_artifact(events_module.propose_keyword_event_candidates(
        {'records_ref': ref, 'keyword_jaccard': .72}, ctx).data_ref)['groups']
    assert len(groups) == 1 and sorted(groups[0]['member_ids']) == ['r1', 'r2']

    raw = [{'id': 'r1', 'title': '防汛演练', 'summary': ''},
           {'id': 'r2', 'title': '@测试账号 防汛演练', 'summary': ''}]
    ref_raw = ctx.store.put_artifact('s9a', 'records', {'records': raw})
    raw_groups = ctx.store.get_artifact(events_module.propose_keyword_event_candidates(
        {'records_ref': ref_raw, 'keyword_jaccard': .72}, ctx).data_ref)['groups']
    # 历史 artifact（无 normalized_* 字段）回退到原文；但 `tokenize()` 入口内也做归一化，
    # `@测试账号` 同样被清掉 → 两条都只剩 `防汛演练`，合并成 1 组。旧期望 2 组建立在
    # "分词器只认传进来的原文"之上，入口归一化后该前提不再成立。
    assert len(raw_groups) == 1 and sorted(raw_groups[0]['member_ids']) == ['r1', 'r2']


def test_theme_cluster_text_comes_from_normalized_fields(tmp_path, monkeypatch):
    """events.py:92 —— 主题命中必须在归一化文本上做，否则噪声词会伪造主题。"""
    monkeypatch.setattr(events_module.vocabulary, 'cluster_terms', lambda: {'演练': ['诈骗']})
    ctx = RunContext(Store(tmp_path / 'data'), 's9a')
    ref = ctx.store.put_artifact('s9a', 'records', {'records': [
        # 原始标题含 `诈骗`，归一化把它去掉了 → 不该命中「演练」
        {'id': 'r1', 'title': '诈骗 演习', 'summary': '', 'category': '',
         'source_ref': {}, 'normalized_title': '演习', 'normalized_summary': ''},
        # 归一化保留了 `诈骗` → 命中「演练」
        {'id': 'r2', 'title': '诈骗 警情', 'summary': '', 'category': '',
         'source_ref': {}, 'normalized_title': '诈骗 警情', 'normalized_summary': ''},
    ]})
    items = ctx.store.get_artifact(events_module.cluster_event_themes(
        {'records_ref': ref}, ctx).data_ref)['items']
    themes = {item['record_id']: item['candidate_theme'] for item in items}
    assert themes == {'r1': '待人工分类', 'r2': '演练'}


def test_import_records_adds_normalized_fields_without_touching_originals(tmp_path):
    """records.py —— 归一化在 import 之后做一次；原文必须逐字保留给出图与证据用。"""
    path = tmp_path / 'n.xlsx'
    path.write_bytes(_xlsx(['标题', '舆情调性'], [['２０２６年演练 @测试账号', '正面']]))
    # 用构造期捕获：落盘 artifact 的键序被 sort_keys 抹平，字段序只能在这里断言。
    ctx = RunContext(_CaptureStore(), 's9a')
    import_records({'path': str(path), 'sheet_index': 3}, ctx)

    payload = ctx.store.payload
    assert payload['normalization'] == NORMALIZATION_VERSION
    record = payload['records'][0]
    assert record['title'] == '２０２６年演练 @测试账号'
    assert record['normalized_title'] == '2026年演练'
    assert list(record)[-2:] == ['normalized_title', 'normalized_summary']
