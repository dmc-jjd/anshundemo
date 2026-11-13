"""S10 归一化第二批（jieba 分词 + 平台模板前缀剥离）的验收。

三条界线：
    ① `core/text.py` 是唯一分词实现——`dedup` 与 39 处 `words()` 调用点共用它，
       不许再出现第二套分词；
    ② 客户词典必须整词成词（通用词典会把复合地名/类目词切碎），但**单字实词**
       （`人` `车` `火` `水` `死` `伤`）必须保留——用通用停用词表一刀切是这类数据上
       最常见的错误；
    ③ 前缀剥离只剥白名单里的模板串。`地名/机构名 + 冒号` 是账号署名，属信息，
       剥了就是丢数据——这里用反例钉死。

判别式优先：不是"函数没崩"，而是"同一对记录在旧/新规则下得到不同结论"。
"""

from __future__ import annotations

import pytest

from app.schemas import TaskState
from app.storage import Store
from app.tool_executor import RunContext
from core.text import (
    TOKENIZER_VERSION,
    normalize_text,
    strip_boilerplate_prefix,
    tokenize,
)
from core.tools._shared import words
from core.tools.dedup import group_by_representative


# --------------------------------------------------------------------------- #
# V1 jieba 分词质量
# --------------------------------------------------------------------------- #

def test_customer_compounds_come_out_whole():
    """客户词典注入的实证：这几组词在通用词典里都会被切碎（实测见任务书）。"""
    assert '西秀区' in tokenize('西秀区市场监管开展检查')
    assert '黄果树旅游区' in tokenize('黄果树旅游区游客量增长')
    assert '安顺经开区' in tokenize('安顺经开区管委会通报')
    assert '文化旅游' in tokenize('文化旅游市场整治')
    assert '市场监管' in tokenize('西秀区市场监管开展检查')
    # 旧 bigram 会产出 `西秀`/`秀区`/`场监` 这类跨词碎片，新分词不应再有。
    assert not {'西秀', '秀区', '场监', '管开'} & set(tokenize('西秀区市场监管开展检查'))


def test_function_word_singletons_are_dropped():
    tokens = tokenize('这是他们的一个什么问题')
    assert '的' not in tokens and '一个' not in tokens and '什么' not in tokens
    # 旧 bigram 的碎片同样不该出现
    assert not {'的一', '个什', '么问'} & set(tokens)


def test_single_char_content_words_are_kept():
    """单字实词是突发事件标题的核心信号，绝不能随虚词一起被停用词表吃掉。"""
    from core.text import _keep_token

    tokens = tokenize('一人死亡两人受伤')
    assert '人' in tokens and '死亡' in tokens and '受伤' in tokens
    assert '车' in tokenize('大火烧毁三辆车')
    assert '伤' in tokenize('三人伤')
    assert '路' in tokenize('雨天路滑车辆侧翻')
    # 规则本身：单字实词全放行、单字虚词全挡——`火`/`水`/`死` 是否**单独成 token**
    # 取决于 jieba 把它们与邻字组成什么词（`火烧`/`河水`），那是切法问题，不是丢弃。
    assert all(_keep_token(word) for word in '人车火水死伤路埋屋')
    assert not any(_keep_token(word) for word in '的了是在和有就都而及与着或')
    # 单字虚词不出现在真实标题的 token 里。
    assert '的' not in tokenize('装睡的人永远叫不醒')


def test_pure_punctuation_and_short_ascii_are_dropped():
    tokens = tokenize('火灾!!! ~~~ 😂 ok a 5g基站')
    assert '!' not in tokens and '~' not in tokens and '😂' not in tokens
    assert 'ok' in tokens and 'a' not in tokens
    # jieba 会把 `5g基站` 切成 ASCII 段 + 汉字段，两段都保留即可。
    assert '5g' in tokens and '基站' in tokens


def test_tokenize_is_deterministic():
    """HMM=False 的意义：同一输入连跑三次必须逐字相同。"""
    sample = '黄果树旅游区游客投诉景区门票价格'
    assert tokenize(sample) == tokenize(sample) == tokenize(sample)


def test_tokenize_tolerates_empty_and_noise_only_input():
    assert tokenize(None) == [] and tokenize('') == [] and tokenize('   ') == []
    assert tokenize('@某账号 @另一账号') == []
    assert tokenize('!！?？~~~ 😂') == []


def test_tokenize_version_is_pinned():
    """分词器版本与 `requirements.txt` 的 jieba pin 对应；换版本必须同时改这个串。"""
    assert TOKENIZER_VERSION.startswith('jieba-')


def test_words_is_exactly_tokenize_as_a_set():
    """39 个调用点共用 `words()`；它与 `tokenize` 不允许有第二套口径。"""
    text = '安顺经开区管委会通报火灾事故'
    assert words(text) == set(tokenize(text))


# --------------------------------------------------------------------------- #
# V2 平台模板前缀剥离
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('title, expected', [
    ('炸裂💥新闻：当事人实名举报', '当事人实名举报'),
    ('炸裂新闻：当事人实名举报', '当事人实名举报'),
    ('突发！一大棚深夜起火', '一大棚深夜起火'),
    ('突发:一大棚深夜起火', '一大棚深夜起火'),
    ('速看！这些路段将实行交通管制', '这些路段将实行交通管制'),
    ('来源：某市林业局_林业产业', '某市林业局_林业产业'),
    ('//@张三://@李四:齐伯镇道路施工扰民', '齐伯镇道路施工扰民'),
])
def test_boilerplate_prefixes_are_stripped(title, expected):
    assert normalize_text(title) == expected


@pytest.mark.parametrize('title', [
    '关岭：某项工作开展情况通报',
    '安顺：城区停水通知',
    '西秀区：中小学招生方案公布',
    '平坝：市场监管开展检查',
    '镇宁供电局：计划停电公告',
    '安顺学院：招生简章发布',
])
def test_account_and_place_prefixes_are_never_stripped(title):
    """`X：` 是账号名/地名/机构名——是信息不是噪声。剥掉就是丢信号。"""
    word = title.split('：')[0]
    assert normalize_text(title).startswith(word)


@pytest.mark.parametrize('title', ['炸裂💥新闻：', '突发！', '速看', '来源：', '//@张三:'])
def test_guardrail_keeps_original_when_remainder_is_too_short(title):
    """整条标题就是前缀时不许剥成空串——空标题会伪造出一个"无内容事件组"。"""
    assert strip_boilerplate_prefix(title) == title
    assert normalize_text(title) != ''


def test_guardrail_keeps_short_content_after_prefix():
    """剩 2 字（< 4 字）同样保留原文，宁可留前缀也不留空壳。"""
    assert strip_boilerplate_prefix('突发：车祸') == '突发：车祸'
    # 剩 4 字即达标，可以剥。
    assert strip_boilerplate_prefix('突发：车祸现场') == '车祸现场'


def test_forward_chain_prefix_is_stripped_before_mention_cleanup():
    """`//@某某:` 本身就是一个 @提及——剥离必须在提及清理**之前**，否则链就碎了。"""
    assert normalize_text('//@张三://@李四:齐伯镇道路施工扰民') == '齐伯镇道路施工扰民'
    # 单独的 `@提及`（不在链里）仍按第一批规则清掉，行为不变。
    assert normalize_text('@平安抚顺 回复了：已处理') == '回复了:已处理'


def test_strip_is_idempotent():
    once = normalize_text('炸裂💥新闻：当事人实名举报')
    assert normalize_text(once) == once


# --------------------------------------------------------------------------- #
# V3 过合并的判别式回归（第二批的核心目的）
# --------------------------------------------------------------------------- #

def test_records_sharing_only_a_template_prefix_no_longer_merge():
    """只有模板前缀相同的两条记录，旧规则会合并（共享 `炸裂`/`新闻` 等 bigram），
    新规则剥掉前缀后正文完全不同，必须分开。

    这是第一批点名的那类过合并的最小复现：前缀是平台模板，不是事件内容。
    """
    records = [
        {'id': 'a', 'title': '炸裂💥新闻：当事人实名举报', 'summary': ''},
        {'id': 'b', 'title': '炸裂💥新闻：装睡的人永远叫不醒', 'summary': ''},
    ]
    assert [g['member_ids'] for g in group_by_representative(records, .65)['groups']] == [['a'], ['b']]


def test_shared_prefix_does_not_hide_real_similarity():
    """前提到正文相同则该合并——护栏不能反过来把真合并也拆掉。"""
    records = [
        {'id': 'a', 'title': '炸裂💥新闻：一大棚深夜起火两人死亡', 'summary': ''},
        {'id': 'b', 'title': '突发：一大棚深夜起火两人死亡', 'summary': ''},
    ]
    groups = group_by_representative(records, .65)['groups']
    assert [g['member_ids'] for g in groups] == [['a', 'b']]
