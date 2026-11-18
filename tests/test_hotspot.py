"""首页「今日热点话题」+「社媒热榜占位」用例。

采集流程（B2，见 `app/hotspot.py` 模块 docstring）：
按类别固定查询（走 `core/historical_web.request`；类别来自**客户包** `template.json` 的
`vocabulary.cluster_terms`，每个 label 一条 + 一条涉华国际 = 13 条）→ 结果级过滤（坏标题 /
rerank_score / 日期）→ 事件级去重（URL + 标题 Jaccard）→ 单次结构化 `invoke_agent`（不带 tools）
→ 三道闸门（含 `hotspot_category_invalid`）。

五组判据：
1. 搜索通道与生成模型解耦（`core/config.py::search_endpoint`：REPORT_SEARCH_* 优先、旧行为回退）；
2. 「不编造」机械可证：未配置搜索时**一次搜索与模型调用都不发生、一个 artifact 都不落**；
   引用候选集之外的链接 → 重试 1 次 → 仍不合格报 `hotspot_url_not_from_search` 且不落库；
3. 过滤与去重（脏结果不进候选集、同一事件的多来源变体只留一条、类别短缺只记不阻断）；
4. 缓存语义：`GET` 只读不刷新（搜索与模型调用次数都不变），只有 `POST` 才重新采集；
5. 类别：集合 = 客户包词表键、展示顺序 = `DEFAULT_CATEGORIES` 规范序（包独有的附末尾）；
   查询数 = 12+1、每条含 `after:` 且 ≤128 字符；
   类别闸门报 `hotspot_category_invalid`；API 返回体带 `categories`；前端 TAB 契约用接口值。
"""
import json
import pathlib
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import hotspot, main
from app.config import PACKAGE_DIR
from app.storage import Store

REPO = pathlib.Path(__file__).resolve().parents[1]
# 类别集合来自客户包词表、展示顺序来自基座规范序（`categories()` 统一解析）
VALID_CATEGORIES = list(hotspot.categories())
PER_CATEGORY = 3          # 每个类别返回 3 条（= CATEGORY_MIN，不触发放宽查询）
EVENT_WORDS = ('暴雨', '地铁', '学校', '医院', '景区', '高铁', '港口', '桥梁', '社区', '工厂',
               '农田', '水库', '市场', '电厂', '道路', '公园', '仓库', '车站', '码头', '隧道')


def category_index(category):
    return CATEGORIES_INDEX[category]


CATEGORIES_INDEX = {category: index for index, category in enumerate(VALID_CATEGORIES, 1)}


def candidate_urls(per_category=PER_CATEGORY):
    """候选集 URL（与 `search_stub()` 造的一致）：类别 1..12 × 该类别第 1..n 条。"""
    return [f'https://news.example.com/{index}/{row}'
            for index in range(1, len(VALID_CATEGORIES) + 1) for row in range(1, per_category + 1)]


def items(count=30, category=None, urls=None):
    """合法条目：url 取自候选集，30 个互不相同，`rank` 从 1 连续编到 30。"""
    pool = urls or candidate_urls()
    rows = []
    for index in range(count):
        rows.append({'rank': index + 1, 'title': f'第{index + 1}条要闻',
                     'summary': f'这是第{index + 1}条要闻的一句话摘要，只陈述事实。',
                     'category': category or VALID_CATEGORIES[index % len(VALID_CATEGORIES)],
                     'url': pool[index % len(pool)], 'source': '新闻站点'})
    return rows


def _category_of(query):
    """查询串 → 类别：`{label} 热点 新闻 after:` 前缀是稳定判据；涉华国际那条返回 None。"""
    for label in VALID_CATEGORIES:
        if query.startswith(f'{label} {hotspot.CATEGORY_QUERY_SUFFIX}'):
            return label
    return None


def search_stub(per_category=PER_CATEGORY, error=None, extra=None, drop_categories=()):
    """`core.historical_web.request` 桩：每个类别返回 per_category 条互不相似的结果。

    `extra` 用来注入脏结果（低分 / 旧日期 / 坏标题 / 重复事件），验证两级过滤。
    `drop_categories` 里的类别返回 0 条（验证类别短缺只记录不阻断）。
    """
    calls = []

    def request(kind, args, ctx):
        assert kind == 'search'
        calls.append(args['query'])
        if error is not None:
            raise error
        category = _category_of(args['query'])
        if category is None or category in drop_categories:
            return {'results': []}
        index = category_index(category)
        rows = []
        for row in range(1, per_category + 1):
            word = EVENT_WORDS[(index * per_category + row) % len(EVENT_WORDS)]
            rows.append({'title': f'{category}{word}{row}',
                         'url': f'https://news.example.com/{index}/{row}',
                         'summary': f'查询{index}的第{row}条长摘要' + '，补充说明' * 20,
                         'snippet': f'查询{index}的第{row}条短摘要',
                         'date': None, 'rerank_score': 2.0 + row / 10, 'authority': 3,
                         'site_name': '新闻站点'})
        if extra:
            rows.extend(extra.get(category, []))
        return {'results': rows}

    request.calls = calls
    return request


class Model:
    """`context.model_adapter` 桩：按调用序返回预设 payload（不足时重复最后一份）。"""

    def __init__(self, *payloads, error=None):
        self.payloads = list(payloads) or [{'items': items()}]
        self.error = error
        self.calls = 0
        self.seen = []

    async def __call__(self, role_id, payload):
        self.calls += 1
        self.seen.append(payload)
        assert role_id == 'hotspot_collector'
        # payload 契约：日期 / 窗口 / 条数 / 类别 / 候选集都在
        assert payload['item_count'] == 30 and payload['categories'] == VALID_CATEGORIES
        assert payload['window']['from'] < payload['window']['to']
        assert payload['search_results'] and payload['must_search_online'] is True
        if self.error is not None:
            raise self.error
        return self.payloads[min(self.calls - 1, len(self.payloads) - 1)]


@pytest.fixture()
def store(tmp_path, monkeypatch):
    local = Store(tmp_path)
    monkeypatch.setattr(main, 'store', local)
    monkeypatch.delenv('REPORT_SEARCH_URL', raising=False)
    monkeypatch.delenv('REPORT_SEARCH_KEY', raising=False)
    return local


@pytest.fixture()
def no_config_search(monkeypatch):
    """搜索未配置（ark 生成端点 + 无 REPORT_SEARCH_*）：返回 409 的那一档。"""
    import core.config as config

    monkeypatch.setattr(config, 'SEARCH_URL', '')
    monkeypatch.setattr(config, 'SEARCH_KEY', '')
    monkeypatch.setattr(config, 'MODEL_URL', 'https://ark.cn-beijing.volces.com/api/v3')
    monkeypatch.setattr(config, 'MODEL_KEY', 'ark-key')


@pytest.fixture()
def configured(monkeypatch):
    import core.config as config

    monkeypatch.setattr(config, 'SEARCH_URL', 'https://api.deepseek.com/v1')
    monkeypatch.setattr(config, 'SEARCH_KEY', 'search-key')


def artifacts(store) -> int:
    return len(list((store.root / 'artifacts').glob('*.json')))


def client() -> TestClient:
    return TestClient(main.app)


def web_usage(store) -> list[dict]:
    return [event for event in store.events(hotspot.OWNER_TASK) if event['type'] == 'web_usage']


# ---------------------------------------------------------------- 搜索通道解耦


def test_search_endpoint_prefers_report_search_credentials(monkeypatch):
    import core.config as config

    monkeypatch.setattr(config, 'SEARCH_URL', 'https://search.example.com/v1')
    monkeypatch.setattr(config, 'SEARCH_KEY', 'search-key')
    monkeypatch.setattr(config, 'MODEL_URL', 'https://ark.cn-beijing.volces.com/api/v3')
    monkeypatch.setattr(config, 'MODEL_KEY', 'ark-key')
    assert config.search_endpoint() == ('https://search.example.com/v1', 'search-key')


def test_search_endpoint_falls_back_only_to_deepseek_model(monkeypatch):
    import core.config as config

    monkeypatch.setattr(config, 'SEARCH_URL', '')
    monkeypatch.setattr(config, 'SEARCH_KEY', '')
    monkeypatch.setattr(config, 'MODEL_URL', 'https://api.deepseek.com')
    monkeypatch.setattr(config, 'MODEL_KEY', 'legacy-key')
    assert config.search_endpoint() == ('https://api.deepseek.com', 'legacy-key')

    monkeypatch.setattr(config, 'MODEL_URL', 'https://ark.cn-beijing.volces.com/api/v3')
    with pytest.raises(ValueError, match=config.SEARCH_ERROR):
        config.search_endpoint()


def test_tools_url_keeps_legacy_v1_path():
    from core.historical_web import tools_url

    assert tools_url('https://api.deepseek.com', 'search') == 'https://api.deepseek.com/v1/tools/search'
    assert tools_url('https://api.deepseek.com/v1/', 'fetch') == 'https://api.deepseek.com/v1/tools/fetch'


def test_categories_use_the_customer_set_in_canonical_order():
    """客户包声明了 cluster_terms → 集合 = 该包词表键，顺序 = `DEFAULT_CATEGORIES` 规范序（交集）。"""
    template = json.loads((PACKAGE_DIR / 'template.json').read_text(encoding='utf-8'))
    labels = list(template['vocabulary']['cluster_terms'])
    assert len(labels) == 12
    known = set(labels)
    canonical = [c for c in hotspot.DEFAULT_CATEGORIES if c in known]
    assert list(hotspot.categories()) == canonical          # 顺序按规范序（不是词表键序）
    assert set(hotspot.categories()) == known               # 集合仍来自客户包
    assert VALID_CATEGORIES == canonical
    # 展示顺序 = 用户口径：社会民生打头、自然灾害收尾
    assert VALID_CATEGORIES[0] == '社会民生' and VALID_CATEGORIES[-1] == '自然灾害'


def test_categories_order_ignores_the_package_key_order_and_appends_extras(tmp_path):
    """客户包键序故意打乱 + 含规范序外的类别 → 仍按规范序排，包独有的附在末尾。"""
    from core.tools import vocabulary

    scrambled = ['自然灾害', '经济', '医疗卫生', '社会民生', '环境保护']
    pkg = tmp_path / 'scrambled_package'
    pkg.mkdir()
    (pkg / 'manifest.yaml').write_text(
        'package: scrambled_package\nreport_type: test\nversion: 0.0.0\n'
        'template: template.json\nprompts: prompts/\n', encoding='utf-8')
    (pkg / 'template.json').write_text(
        json.dumps({'vocabulary': {'cluster_terms': {label: [label] for label in scrambled}}}),
        encoding='utf-8')
    try:
        vocabulary.configure(pkg)
        got = hotspot.categories()
    finally:
        vocabulary.configure(PACKAGE_DIR)
    known = set(scrambled)
    assert got == tuple(c for c in hotspot.DEFAULT_CATEGORIES if c in known) + ('经济',)
    assert got[:2] == ('社会民生', '环境保护')   # 规范序在前的先出
    assert got[-1] == '经济'                    # 规范序外的附末尾
    assert '经济' not in hotspot.DEFAULT_CATEGORIES
    assert hotspot.categories() == tuple(VALID_CATEGORIES)  # 恢复到客户包口径


def test_categories_fall_back_to_base_defaults_without_customer_labels(tmp_path):
    """客户包没声明 cluster_terms → 基座默认 12 类（顺序 = 用户展示口径）。"""
    from core.tools import vocabulary

    blank = tmp_path / 'blank_package'
    blank.mkdir()
    (blank / 'manifest.yaml').write_text(
        'package: blank_package\nreport_type: test\nversion: 0.0.0\n'
        'template: template.json\nprompts: prompts/\n', encoding='utf-8')
    (blank / 'template.json').write_text(json.dumps({}), encoding='utf-8')
    try:
        vocabulary.configure(blank)
        assert hotspot.categories() == hotspot.DEFAULT_CATEGORIES
        assert len(hotspot.DEFAULT_CATEGORIES) == 12
        assert len(set(hotspot.DEFAULT_CATEGORIES)) == 12
    finally:
        vocabulary.configure(PACKAGE_DIR)
    assert hotspot.categories() == tuple(VALID_CATEGORIES)


def test_query_plan_is_one_per_category_plus_one_international():
    """查询集 = 客户包每个类别一条 + 一条涉华国际（12+1=13）；每条 ≤128 字符且锁定窗口。"""
    since = '2026-11-10'
    plan = hotspot.queries(since)
    assert len(plan) == len(VALID_CATEGORIES) + 1 == 13
    assert [label for label, _ in plan] == VALID_CATEGORIES + [None]
    for label, query in plan:
        assert f' after:{since}' in query
        assert len(query) <= hotspot.SEARCH_QUERY_MAX
        if label is not None:
            # 查询确实由类别 label 生成（不是别的硬编码清单）
            assert query.startswith(f'{label} {hotspot.CATEGORY_QUERY_SUFFIX}')
    assert plan[-1][1].startswith(hotspot.INTL_QUERY)  # 第 13 条是涉华国际，不预标注类别
    assert len({query for _, query in plan}) == 13


# ---------------------------------------------------------------- 「不编造」硬证据


def test_collect_without_search_credentials_is_409_and_writes_nothing(store, no_config_search, monkeypatch):
    from core import historical_web as web

    search = search_stub()
    model = Model({'items': items()})
    monkeypatch.setattr(web, 'request', search)
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    response = client().post('/api/hotspot/collect')
    assert response.status_code == 409 and response.json()['detail'] == 'search_not_configured'
    # 不编造的机械证据：搜索 0 次、模型 0 次、artifact 0 个、连宿主任务都没建
    assert search.calls == [] and model.calls == 0
    assert artifacts(store) == 0 and store.list_tasks() == []


def test_get_without_cache_never_searches_or_calls_the_model(store, configured, monkeypatch):
    from core import historical_web as web

    search = search_stub()
    model = Model()
    monkeypatch.setattr(web, 'request', search)
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    body = client().get('/api/hotspot').json()
    assert body['available'] is False and body['items'] == []
    # 无缓存也要给窗口（前端头部行要显示「窗口 11-10 ~ 11-13 · 未采集」）与类别（TAB 行）
    assert list(body['window']) == ['from', 'to'] and body['window']['from'] < body['window']['to']
    assert body['categories'] == VALID_CATEGORIES and len(body['categories']) == 12
    assert search.calls == [] and model.calls == 0 and artifacts(store) == 0


# ---------------------------------------------------------------- URL 白名单闸门（防编造核心）


def test_forged_url_is_retried_then_rejected_without_storing(store, configured, monkeypatch):
    from core import historical_web as web

    forged = items()
    forged[0]['url'] = 'https://evil.example.com/fabricated-story'
    model = Model({'items': forged})  # 两次都编造
    monkeypatch.setattr(web, 'request', search_stub())
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    response = client().post('/api/hotspot/collect')
    assert response.status_code == 502
    assert response.json()['detail'].startswith('hotspot_url_not_from_search')
    assert model.calls == 2  # 编造重试恰好 1 次
    assert artifacts(store) == 0  # 伪造数据一条都不落库
    # 重试时把「你引用了不存在的链接」明确告诉过模型
    assert any('不在候选集里' in str(line) for line in model.seen[-1]['correction_errors'])


def test_forged_url_then_fixed_on_retry_succeeds(store, configured, monkeypatch):
    from core import historical_web as web

    forged = items()
    forged[5]['url'] = 'https://evil.example.com/fabricated-story'
    model = Model({'items': forged}, {'items': items()})
    monkeypatch.setattr(web, 'request', search_stub())
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    body = client().post('/api/hotspot/collect').json()
    assert body['available'] is True and len(body['items']) == 30
    assert model.calls == 2 and artifacts(store) == 1


def test_tracking_param_variant_is_accepted_and_canonicalised(store, configured, monkeypatch):
    """实测模型会逐字照抄但改写追踪参数：身份（host+path）相同即接受，落库换回候选原文。"""
    from core import historical_web as web

    drifted = items()
    drifted[0]['url'] = drifted[0]['url'] + '?scm=10001.325_13-325_13.0.0-1-0-0-0.5&_trans_=060008'
    monkeypatch.setattr(web, 'request', search_stub())
    model = Model({'items': drifted})
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    body = client().post('/api/hotspot/collect').json()
    assert model.calls == 1  # 追踪参数差异不触发重试
    assert body['items'][0]['url'] == candidate_urls()[0]  # 落库 url = 候选集原文


def test_duplicate_urls_are_not_enough_for_thirty_items(store, configured, monkeypatch):
    from core import historical_web as web

    repeated = items()
    repeated[1]['url'] = repeated[0]['url']  # 30 条但只有 29 个不同链接
    monkeypatch.setattr(web, 'request', search_stub())
    model = Model({'items': repeated})
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    response = client().post('/api/hotspot/collect')
    assert response.status_code == 502
    assert response.json()['detail'].startswith('hotspot_items_incomplete')
    assert model.calls == 2 and artifacts(store) == 0


@pytest.mark.parametrize('count, accepted', [(29, False), (30, True), (31, False)])
def test_item_count_boundary_is_exactly_thirty(count, accepted, store, configured, monkeypatch):
    """条数边界：29 报错 / 30 通过 / 31 报错（多一条少一条都整份退回）。"""
    from core import historical_web as web

    monkeypatch.setattr(web, 'request', search_stub())
    model = Model({'items': items(count)})
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    response = client().post('/api/hotspot/collect')
    if accepted:
        assert response.status_code == 200 and len(response.json()['items']) == 30
        assert model.calls == 1 and artifacts(store) == 1
        return
    assert response.status_code == 502
    assert response.json()['detail'].startswith('hotspot_schema_invalid')
    assert model.calls == 2 and artifacts(store) == 0
    assert client().get('/api/hotspot').json()['available'] is False


def test_rank_must_be_contiguous_one_to_thirty(store, configured, monkeypatch):
    """rank 跳号（30 条但跳过 17）→ 报错且不落库：序号空洞会直接暴露在前端列表上。"""
    from core import historical_web as web

    gapped = items()
    gapped[16]['rank'] = 18  # 1..16, 18, 18..30：跳过 17
    monkeypatch.setattr(web, 'request', search_stub())
    model = Model({'items': gapped})
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    response = client().post('/api/hotspot/collect')
    assert response.status_code == 502
    detail = response.json()['detail']
    assert detail.startswith('hotspot_schema_invalid') and 'rank_not_contiguous' in detail
    assert model.calls == 2 and artifacts(store) == 0


def test_invalid_category_is_category_invalid(store, configured, monkeypatch):
    from core import historical_web as web

    monkeypatch.setattr(web, 'request', search_stub())
    model = Model({'items': items(30, category='娱乐八卦')})
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    response = client().post('/api/hotspot/collect')
    detail = response.json()['detail']
    assert response.status_code == 502 and detail.startswith('hotspot_category_invalid')
    assert '娱乐八卦' in detail  # 归因到具体条目，便于排查
    assert model.calls == 2 and artifacts(store) == 0
    # 重试时明确把类别约束回给模型
    assert any('categories' in str(line) for line in model.seen[-1]['correction_errors'])


def test_model_failure_is_502_without_writing(store, configured, monkeypatch):
    from core import historical_web as web

    monkeypatch.setattr(web, 'request', search_stub())
    model = Model(error=RuntimeError('model_offline'))
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    response = client().post('/api/hotspot/collect')
    assert response.status_code == 502
    assert response.json()['detail'].startswith('hotspot_model_failed')
    assert artifacts(store) == 0


def test_all_search_failures_is_502_without_writing(store, configured, monkeypatch):
    from core import historical_web as web

    monkeypatch.setattr(web, 'request', search_stub(error=ValueError('historical_search_failed:503')))
    model = Model()
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    response = client().post('/api/hotspot/collect')
    assert response.status_code == 502
    assert response.json()['detail'].startswith('hotspot_search_failed')
    assert model.calls == 0 and artifacts(store) == 0


# ---------------------------------------------------------------- 两级过滤 + 事件级去重


def test_dirty_results_never_reach_the_model(store, configured, monkeypatch):
    from core import historical_web as web

    dirty = {
        '社会民生': [
            {'title': '第A1版:要闻', 'url': 'https://dirty.example.com/a1', 'summary': '报纸索引页',
             'rerank_score': 3.0, 'authority': 4},
            {'title': '社会民生长文', 'url': 'https://dirty.example.com/low', 'summary': '低分',
             'rerank_score': 0.4, 'authority': 4},
            {'title': '社会民生旧闻', 'url': 'https://dirty.example.com/old', 'summary': '窗口外',
             'date': '2020-01-01T00:00:00Z', 'rerank_score': 3.0, 'authority': 4},
            {'title': '社会民生安全验证', 'url': 'https://dirty.example.com/verify', 'summary': '验证页',
             'rerank_score': 3.0, 'authority': 4},
        ]
    }
    monkeypatch.setattr(web, 'request', search_stub(extra=dirty))
    model = Model({'items': items()})
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    client().post('/api/hotspot/collect')
    fed = '\n'.join(model.seen[0]['search_results'])
    for bad in ('dirty.example.com/a1', 'dirty.example.com/low', 'dirty.example.com/old',
                'dirty.example.com/verify'):
        assert bad not in fed


def test_same_event_from_multiple_sources_is_merged(store, configured, monkeypatch):
    from core import historical_web as web

    # 同一事件的两种写法（同一事件、两个来源，仅标点差异）：标题 Jaccard ≥0.6 → 只留权重高的一条
    duplicate = {VALID_CATEGORIES[0]: [
        {'title': '西安政务服务中心挖掘机破坏，警方通报', 'url': 'https://dirty.example.com/dup-high',
         'summary': '同一事件的高权重来源', 'rerank_score': 3.0, 'authority': 4},
        {'title': '西安政务服务中心挖掘机破坏 警方通报', 'url': 'https://dirty.example.com/dup-low',
         'summary': '同一事件的低权重来源', 'rerank_score': 1.6, 'authority': 1},
    ]}
    monkeypatch.setattr(web, 'request', search_stub(extra=duplicate))
    model = Model({'items': items()})
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    client().post('/api/hotspot/collect')
    fed = '\n'.join(model.seen[0]['search_results'])
    assert 'dirty.example.com/dup-high' in fed
    assert 'dirty.example.com/dup-low' not in fed  # 低权重变体被合并掉


def test_excluded_site_is_dropped_from_results(store, configured, monkeypatch):
    from core import historical_web as web

    excluded = {'社会民生': [
        {'title': '社会民生繁体镜像新闻', 'url': 'https://big5.cctv.com/mirror/story',
         'summary': '镜像站', 'rerank_score': 3.0, 'authority': 4},
    ]}
    monkeypatch.setattr(web, 'request', search_stub(extra=excluded))
    model = Model({'items': items()})
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    client().post('/api/hotspot/collect')
    assert 'big5.cctv.com' not in '\n'.join(model.seen[0]['search_results'])


def test_category_shortage_is_recorded_but_does_not_block(store, configured, monkeypatch):
    from core import historical_web as web

    # 4 条/类 → 11 个正常类别 = 44 条候选（丢一类后仍够挑 30 条）
    dropped = VALID_CATEGORIES[-1]
    monkeypatch.setattr(web, 'request', search_stub(per_category=4, drop_categories=(dropped,)))
    pool = [f'https://news.example.com/{index}/{row}'
            for index in range(1, len(VALID_CATEGORIES) + 1) for row in range(1, 5)
            if index != category_index(dropped)]
    model = Model({'items': items(urls=pool)})
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    body = client().post('/api/hotspot/collect').json()
    assert body['available'] is True and body['category_shortage'] == {dropped: 0}
    # 短缺只落库供排查，前端读的 GET 返回体里不出现该字段
    assert 'category_shortage' not in client().get('/api/hotspot').json()


def test_queries_lock_the_window_and_exclude_sites(store, configured, monkeypatch):
    from core import historical_web as web

    search = search_stub()
    monkeypatch.setattr(web, 'request', search)
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', Model({'items': items()}))
    client().post('/api/hotspot/collect')
    since = hotspot.window_for(date.today())['from']
    assert len(search.calls) == len(hotspot.queries(since)) == 13
    for query in search.calls:
        assert f' after:{since}' in query  # 窗口由搜索语法锁定，不靠模型判断
        assert len(query) <= hotspot.SEARCH_QUERY_MAX  # 128 字符硬限制
        for site in hotspot.EXCLUDE_SITES:
            assert f' -site:{site}' in query  # 只用负向排除


def test_query_longer_than_128_chars_is_rejected(monkeypatch):
    with pytest.raises(hotspot.HotspotSearchQueryTooLong, match='search_query_too_long'):
        hotspot.build_query('长' * 130, '2026-11-10')


def test_candidates_are_ordered_by_objective_weight(store, configured, monkeypatch):
    from core import historical_web as web

    scored = {
        VALID_CATEGORIES[0]: [{'title': '西安案件挖掘机破坏高权重', 'url': 'https://dirty.example.com/w-high',
                              'summary': '高权重', 'rerank_score': 3.0, 'authority': 4}],
        VALID_CATEGORIES[1]: [{'title': '产业政策发布中权重', 'url': 'https://dirty.example.com/w-mid',
                              'summary': '中权重', 'rerank_score': 2.0, 'authority': 2}],
    }
    monkeypatch.setattr(web, 'request', search_stub(extra=scored))
    model = Model({'items': items()})
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    client().post('/api/hotspot/collect')
    fed = model.seen[0]['search_results']
    high = next(index for index, line in enumerate(fed) if 'w-high' in line)
    mid = next(index for index, line in enumerate(fed) if 'w-mid' in line)
    assert high < mid  # `rerank_score*2+authority` 高的排在前面（候选序号即排序口径）


# ---------------------------------------------------------------- 采集成功、搜索记账与缓存语义


def test_successful_collect_round_trips_through_get(store, configured, monkeypatch):
    from core import historical_web as web

    monkeypatch.setattr(web, 'request', search_stub())
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', Model({'items': items()}))
    created = client().post('/api/hotspot/collect').json()
    assert created['available'] is True and len(created['items']) == 30
    assert created['window']['from'] < created['window']['to']
    assert created['search_configured'] is True and created['model'] == hotspot.MODEL_NAME
    assert created['categories'] == VALID_CATEGORIES  # TAB 来源：接口返回体
    assert {item['url'] for item in created['items']} <= set(candidate_urls())
    assert store.get_artifact(created['ref'])['items'] == created['items']
    fetched = client().get('/api/hotspot').json()
    assert fetched['items'] == created['items'] and fetched['collected_at'] == created['collected_at']


def test_web_usage_events_equal_fixed_query_count(store, configured, monkeypatch):
    """搜索记账：桩打在 HTTP 层（urlopen），走真 `request()`，故 web_usage 事件是真的。"""
    import io

    from core import historical_web as web

    calls = []

    class Reply:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return io.StringIO(json.dumps(self.data))

        def __exit__(self, *args):
            pass

    def urlopen(req, timeout=None):
        calls.append(req.full_url)
        query = json.loads(req.data.decode('utf-8'))['query']
        category = _category_of(query)
        # 涉华国际那条也必须有结果（billable 只在 results 非空时为真）
        index = 0 if category is None else category_index(category)
        label = '涉华国际' if category is None else category
        return Reply({'results': [{'title': f'{label}{EVENT_WORDS[(index + row) % len(EVENT_WORDS)]}{row}',
                                   'url': f'https://news.example.com/{index}/{row}',
                                   'summary': '摘要' * 40, 'rerank_score': 2.0, 'authority': 3,
                                   'site_name': '新闻站点'} for row in range(1, PER_CATEGORY + 1)]})

    monkeypatch.setattr(web.urllib.request, 'urlopen', urlopen)
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', Model({'items': items()}))
    client().post('/api/hotspot/collect')
    # 查询计划每条一次搜索 = 13 次；每次都由 request() 写一条 web_usage 且 billable 为真
    assert len(calls) == len(hotspot.queries(date.today().isoformat())) == 13
    assert all(url.startswith('https://api.deepseek.com/v1/tools/search') for url in calls)
    usage = web_usage(store)
    assert len(usage) == 13
    assert all(event['operation'] == 'search' and event['billable'] is True for event in usage)


def test_partial_search_failure_still_collects(store, configured, monkeypatch):
    from core import historical_web as web

    # 首条查询直接报错：其余 11 个类别 × 4 = 44 条候选仍够挑 30 条 → 单条失败不拖垮整轮
    failed = VALID_CATEGORIES[0]
    original = search_stub(per_category=4)

    def request(kind, args, ctx):
        if args['query'].startswith(f'{failed} {hotspot.CATEGORY_QUERY_SUFFIX}'):
            raise ValueError('historical_search_failed:503')
        return original(kind, args, ctx)

    monkeypatch.setattr(web, 'request', request)
    pool = [f'https://news.example.com/{index}/{row}'
            for index in range(1, len(VALID_CATEGORIES) + 1) for row in range(1, 5)
            if index != category_index(failed)]
    model = Model({'items': items(urls=pool)})
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    body = client().post('/api/hotspot/collect').json()
    assert body['available'] is True and model.calls == 1


def test_get_never_refreshes_and_post_always_does(store, configured, monkeypatch):
    from core import historical_web as web

    search = search_stub()
    model = Model({'items': items()})
    monkeypatch.setattr(web, 'request', search)
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    first = client().post('/api/hotspot/collect').json()
    client().get('/api/hotspot')
    client().get('/api/hotspot')
    assert model.calls == 1  # GET 只读缓存，模型调用次数不变
    assert len(search.calls) == len(hotspot.queries(date.today().isoformat())) == 13  # GET 也不重新搜索
    second = client().post('/api/hotspot/collect').json()
    assert model.calls == 2 and len(search.calls) == 26
    assert second['collected_at'] > first['collected_at']


# ---------------------------------------------------------------- 用户截图模拟社媒热榜（2026-11-18）


@pytest.mark.parametrize('platform', ['weibo', 'douyin', 'toutiao', 'baidu'])
def test_social_hotlist_contains_screenshot_demo(platform):
    body = client().get('/api/social-hotlist', params={'platform': platform}).json()
    assert body['platform'] == platform and body['collected_at'] is None
    assert body['demo'] is True and body['source'] == '用户截图模拟数据'
    assert len(body['items']) == 20
    assert [row['rank'] for row in body['items']] == list(range(1, 21))
    assert all(row['title'] and row['heat'] and row['sentiment'] in ('中', '正') for row in body['items'])
    first = {'weibo': ('A股', '468.4亿'), 'douyin': ('普京抵达深圳', '1218.4万'),
             'toutiao': ('深圳机场停满各国领导人…', '4006.7万'),
             'baidu': ('习近平会见加拿大总理卡尼', '790.4万')}
    assert (body['items'][0]['title'], body['items'][0]['heat']) == first[platform]


def test_social_hotlist_rejects_unknown_platform():
    response = client().get('/api/social-hotlist', params={'platform': 'zhihu'})
    assert response.status_code == 422 and response.json()['detail'] == 'invalid_platform'


# ---------------------------------------------------------------- 前端 TAB 契约（类别来自接口）


def test_api_carries_the_customer_categories_for_the_tab_row(store):
    """`/api/hotspot` 恒带 `categories`（无缓存时也有）：前端 TAB 行只认这个字段。"""
    body = client().get('/api/hotspot').json()
    assert body['categories'] == VALID_CATEGORIES
    assert len(body['categories']) == 12


def test_frontend_tab_contract_keeps_dom_ids_and_reads_api_categories():
    """DOM 契约：六个既有 id 不动，新增 hotspotTabs；JS 不写死类别名（全部从接口取）。"""
    html = (REPO / 'app/static/index.html').read_text(encoding='utf-8')
    for element_id in ('hotspotPanel', 'hotspotTitle', 'hotspotMeta',
                       'hotspotCollect', 'hotspotError', 'hotspotList', 'hotspotTabs'):
        assert f'id="{element_id}"' in html, element_id
    js = (REPO / 'app/static/hotspot.js').read_text(encoding='utf-8')
    assert "getElementById('hotspotTabs')" in js
    assert 'body.categories' in js  # 类别清单来自接口返回体
    assert "'全部'" in js or '"全部"' in js  # 首项固定「全部」
    # 换客户零改动：JS/HTML 里不得出现客户包类别名
    for label in VALID_CATEGORIES:
        assert label not in js, label
        assert label not in html, label


# ---------------------------------------------------------------- 门禁面不移动


def test_homepage_routes_stay_out_of_openapi():
    spec = client().get('/openapi.json').json()
    paths = spec['paths']
    assert '/api/hotspot' not in paths and '/api/hotspot/collect' not in paths
    assert '/api/social-hotlist' not in paths
    assert len(paths) == 49
    routes = [(method.upper(), path) for path, ops in paths.items() for method in ops]
    assert len(routes) == 52
