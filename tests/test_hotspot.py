"""首页「今日热点话题」+「社媒热榜占位」用例。

采集流程（B2，见 `app/hotspot.py` 模块 docstring）：
按类别固定查询（走 `core/historical_web.request`）→ 结果级过滤（坏标题 / rerank_score / 日期）
→ 事件级去重（URL + 标题 Jaccard）→ 单次结构化 `invoke_agent`（不带 tools）→ 三道闸门。

四组判据：
1. 搜索通道与生成模型解耦（`core/config.py::search_endpoint`：REPORT_SEARCH_* 优先、旧行为回退）；
2. 「不编造」机械可证：未配置搜索时**一次搜索与模型调用都不发生、一个 artifact 都不落**；
   引用候选集之外的链接 → 重试 1 次 → 仍不合格报 `hotspot_url_not_from_search` 且不落库；
3. 过滤与去重（脏结果不进候选集、同一事件的多来源变体只留一条、类别短缺只记不阻断）；
4. 缓存语义：`GET` 只读不刷新（搜索与模型调用次数都不变），只有 `POST` 才重新采集。
"""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import hotspot, main
from app.storage import Store

VALID_CATEGORIES = list(hotspot.CATEGORIES)
PER_CATEGORY = 3          # 每个类别返回 3 条（= CATEGORY_MIN，不触发放宽查询）
EVENT_WORDS = ('暴雨', '地铁', '学校', '医院', '景区', '高铁', '港口', '桥梁', '社区', '工厂',
               '农田', '水库', '市场', '电厂', '道路', '公园', '仓库', '车站', '码头', '隧道')


def category_index(category):
    return CATEGORIES_INDEX[category]


CATEGORIES_INDEX = {category: index for index, category in enumerate(VALID_CATEGORIES, 1)}


def candidate_urls(per_category=PER_CATEGORY):
    """候选集 URL（与 `search_stub()` 造的一致）：类别 1..7 × 该类别第 1..n 条。"""
    return [f'https://news.example.com/{index}/{row}'
            for index in range(1, len(VALID_CATEGORIES) + 1) for row in range(1, per_category + 1)]


def items(count=20, category=None, urls=None):
    """合法条目：url 取自候选集，20 个互不相同。"""
    pool = urls or candidate_urls()
    rows = []
    for index in range(count):
        rows.append({'rank': index + 1, 'title': f'第{index + 1}条要闻',
                     'summary': f'这是第{index + 1}条要闻的一句话摘要，只陈述事实。',
                     'category': category or VALID_CATEGORIES[index % len(VALID_CATEGORIES)],
                     'url': pool[index % len(pool)], 'source': '新闻站点'})
    return rows


def _category_of(query):
    """查询串 → 类别（`{模板}` 的 `after:` 之前那一段是稳定前缀）。"""
    for table in (hotspot.CATEGORY_QUERIES, hotspot.BROADER_QUERIES):
        for category, template in table.items():
            if query.startswith(template.split(' after:')[0]):
                return category
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
        assert payload['item_count'] == 20 and payload['categories'] == VALID_CATEGORIES
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


def test_category_queries_cover_the_seven_categories():
    assert tuple(hotspot.CATEGORY_QUERIES) == tuple(VALID_CATEGORIES)
    assert set(hotspot.BROADER_QUERIES) <= set(VALID_CATEGORIES)
    assert all('after:' in query for query in hotspot.CATEGORY_QUERIES.values())


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
    # 无缓存也要给窗口（前端头部行要显示「窗口 11-10 ~ 11-13 · 未采集」）
    assert list(body['window']) == ['from', 'to'] and body['window']['from'] < body['window']['to']
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
    assert body['available'] is True and len(body['items']) == 20
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


def test_duplicate_urls_are_not_enough_for_twenty_items(store, configured, monkeypatch):
    from core import historical_web as web

    repeated = items()
    repeated[1]['url'] = repeated[0]['url']  # 20 条但只有 19 个不同链接
    monkeypatch.setattr(web, 'request', search_stub())
    model = Model({'items': repeated})
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    response = client().post('/api/hotspot/collect')
    assert response.status_code == 502
    assert response.json()['detail'].startswith('hotspot_items_incomplete')
    assert model.calls == 2 and artifacts(store) == 0


def test_invalid_item_count_is_schema_invalid_and_not_stored(store, configured, monkeypatch):
    from core import historical_web as web

    monkeypatch.setattr(web, 'request', search_stub())
    model = Model({'items': items(19)})
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    response = client().post('/api/hotspot/collect')
    assert response.status_code == 502
    assert response.json()['detail'].startswith('hotspot_schema_invalid')
    assert model.calls == 2 and artifacts(store) == 0
    assert client().get('/api/hotspot').json()['available'] is False


def test_invalid_category_is_schema_invalid(store, configured, monkeypatch):
    from core import historical_web as web

    monkeypatch.setattr(web, 'request', search_stub())
    model = Model({'items': items(20, category='娱乐八卦')})
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    response = client().post('/api/hotspot/collect')
    assert response.status_code == 502 and 'hotspot_schema_invalid' in response.json()['detail']
    assert artifacts(store) == 0


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
    duplicate = {'治安': [
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

    # 4 条/类 → 6 个正常类别 = 24 条候选（丢一类后仍够挑 20 条）
    monkeypatch.setattr(web, 'request', search_stub(per_category=4, drop_categories=('国际',)))
    pool = [f'https://news.example.com/{index}/{row}'
            for index in range(1, len(VALID_CATEGORIES) + 1) for row in range(1, 5)
            if index != category_index('国际')]
    model = Model({'items': items(urls=pool)})
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', model)
    body = client().post('/api/hotspot/collect').json()
    assert body['available'] is True and body['category_shortage'] == {'国际': 0}
    # 短缺只落库供排查，前端读的 GET 返回体里不出现该字段
    assert 'category_shortage' not in client().get('/api/hotspot').json()


def test_queries_lock_the_window_and_exclude_sites(store, configured, monkeypatch):
    from core import historical_web as web

    search = search_stub()
    monkeypatch.setattr(web, 'request', search)
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', Model({'items': items()}))
    client().post('/api/hotspot/collect')
    since = hotspot.window_for(date.today())['from']
    assert len(search.calls) == len(hotspot.CATEGORY_QUERIES)
    for query in search.calls:
        assert f' after:{since}' in query  # 窗口由搜索语法锁定，不靠模型判断
        for site in hotspot.EXCLUDE_SITES:
            assert f' -site:{site}' in query  # 只用负向排除
        assert len(query) <= hotspot.SEARCH_QUERY_MAX


def test_query_longer_than_128_chars_is_rejected(monkeypatch):
    with pytest.raises(hotspot.HotspotSearchQueryTooLong, match='search_query_too_long'):
        hotspot.build_query('长' * 130, '2026-11-10')


def test_candidates_are_ordered_by_objective_weight(store, configured, monkeypatch):
    from core import historical_web as web

    scored = {
        '治安': [{'title': '西安案件挖掘机破坏高权重', 'url': 'https://dirty.example.com/w-high',
                'summary': '高权重', 'rerank_score': 3.0, 'authority': 4}],
        '经济': [{'title': '产业政策发布中权重', 'url': 'https://dirty.example.com/w-mid',
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
    assert created['available'] is True and len(created['items']) == 20
    assert created['window']['from'] < created['window']['to']
    assert created['search_configured'] is True and created['model'] == hotspot.MODEL_NAME
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
        index = category_index(category)
        return Reply({'results': [{'title': f'{category}{EVENT_WORDS[(index + row) % len(EVENT_WORDS)]}{row}',
                                   'url': f'https://news.example.com/{index}/{row}',
                                   'summary': '摘要' * 40, 'rerank_score': 2.0, 'authority': 3,
                                   'site_name': '新闻站点'} for row in range(1, PER_CATEGORY + 1)]})

    monkeypatch.setattr(web.urllib.request, 'urlopen', urlopen)
    monkeypatch.setattr(hotspot, 'MODEL_ADAPTER', Model({'items': items()}))
    client().post('/api/hotspot/collect')
    # 固定查询集每条一次搜索 = 7 次；每次都由 request() 写一条 web_usage 且 billable 为真
    assert len(calls) == len(hotspot.CATEGORY_QUERIES) == 7
    assert all(url.startswith('https://api.deepseek.com/v1/tools/search') for url in calls)
    usage = web_usage(store)
    assert len(usage) == len(hotspot.CATEGORY_QUERIES)
    assert all(event['operation'] == 'search' and event['billable'] is True for event in usage)


def test_partial_search_failure_still_collects(store, configured, monkeypatch):
    from core import historical_web as web

    # 首条查询直接报错：其余 6 × 4 = 24 条候选仍够挑 20 条 → 单条失败不拖垮整轮
    original = search_stub(per_category=4)

    def request(kind, args, ctx):
        if '社会民生' in args['query']:
            raise ValueError('historical_search_failed:503')
        return original(kind, args, ctx)

    monkeypatch.setattr(web, 'request', request)
    pool = [f'https://news.example.com/{index}/{row}'
            for index in range(2, len(VALID_CATEGORIES) + 1) for row in range(1, 5)]
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
    assert len(search.calls) == len(hotspot.CATEGORY_QUERIES)  # GET 也不重新搜索
    second = client().post('/api/hotspot/collect').json()
    assert model.calls == 2 and len(search.calls) == 2 * len(hotspot.CATEGORY_QUERIES)
    assert second['collected_at'] > first['collected_at']


# ---------------------------------------------------------------- 社媒热榜占位


@pytest.mark.parametrize('platform', ['weibo', 'douyin', 'toutiao', 'baidu'])
def test_social_hotlist_is_empty_placeholder(platform):
    body = client().get('/api/social-hotlist', params={'platform': platform}).json()
    assert body == {'platform': platform, 'collected_at': None, 'items': []}


def test_social_hotlist_rejects_unknown_platform():
    response = client().get('/api/social-hotlist', params={'platform': 'zhihu'})
    assert response.status_code == 422 and response.json()['detail'] == 'invalid_platform'


# ---------------------------------------------------------------- 门禁面不移动


def test_homepage_routes_stay_out_of_openapi():
    spec = client().get('/openapi.json').json()
    paths = spec['paths']
    assert '/api/hotspot' not in paths and '/api/hotspot/collect' not in paths
    assert '/api/social-hotlist' not in paths
    assert len(paths) == 49
    routes = [(method.upper(), path) for path, ops in paths.items() for method in ops]
    assert len(routes) == 52
