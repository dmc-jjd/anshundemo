"""首页「今日热点话题」：联网采集最近 3 天中国要闻 20 条。

采集形状（B2：固定查询 → 两级过滤 → 单次结构化）：

    ① 按类别逐条查（`CATEGORY_QUERIES`，7 条，`after:YYYY-MM-DD` 锁定窗口）
       —— 换口径只改这里；实测「通用要闻查询」会被报纸索引页、研报、晨会纪要污染，
       而「按类别逐条查」返回的内容对路（105 条返回 / 80 条达标）。
       站点约束**只用负向 `-site:` 黑名单**（`EXCLUDE_SITES`）：实测 `site:` 白名单会把真实
       治安/民生热点滤成政策通稿（治安达标 0 条、经济查询直接被 128 字符上限拒）。`query`
       超过 128 字符报 `search_query_too_long`，不静默截断。
    ② 两级过滤：结果级（坏标题 / rerank_score<1.5 / 排除站点 / 日期不在窗口）+ 事件级（URL 去重后
       按标题 Jaccard≥0.6 合并同一事件的多来源变体，保留 `rerank_score*2+authority` 更高的一条）。
       某类别达标不足 3 条时用更宽的查询（`BROADER_QUERIES`）重试一次，仍不足则记
       `category_shortage` 继续，不阻断整体。
       候选集排序口径：`rerank_score*2+authority` 降序为主，`date` 新的优先做 tie-break
       （该顺序就是喂给模型的「候选序号」，模型在此基础上做最终挑选与分类微调）。
    ③ 候选集按客观权重粗排后喂模型（上限 `MAX_SEARCH_RESULTS`），一次 `invoke_agent`（**不带 tools**）：
       模型只在候选集里挑 20 条、做最后排序与分类微调。
    ④ 硬校验：恰好 20 条 / 7 类枚举 / http(s) / **每条 url 必须命中候选集 URL 集合** /
       去重后不足 20 条即 `hotspot_items_incomplete`。

「不编造」落在三处，都可机械验证：
1. **搜索凭据先于一切**：`collect()` 第一件事是 `search_endpoint()`；未配置直接抛
   `search_not_configured`，此时一次搜索、一次模型调用、一个 artifact 都不会发生。
2. **URL 白名单闸门**（防编造核心）：模型只能引用候选集里出现过的链接；出现任何陌生链接就
   重试 1 次（并把「你引用了不存在的链接」明确回给模型），仍不合格抛
   `hotspot_url_not_from_search`，残缺或伪造的数据**不落库**。链接身份按 host+path 判定
   （实测模型会照抄但改写追踪参数），命中后**落库 url 一律换回候选集原文**——前端永远指向
   搜索实际返回的链接。
3. **提示词层**：角色边界写明只能引用给定 LINK；窗口由 `after:` 查询语法与 date 复核双重约束，
   不靠模型自己判断「最近三天」。

成本口径（实测）：7 条查询 + 1 次生成 ≈ **¥0.035**（Search 计费 ¥5/1000 次成功请求，只对
`results` 非空的计费）+ 一次生成的 token 费。搜索次数与 billable 由 `web.request()` 自动记进
`web_usage` 事件，不需要额外埋点。

字段分工（官方响应字段）：喂模型用 `title` + `summary`（长摘要 600—800 字，截断到 220 字控 token）；
前端展示用 `title` + `snippet`（短摘要，由 GET 返回体带出）；`url` 原样用（白名单集合）；
`date` 用来复核是否落在窗口内；`rerank_score`（0—3，≥1.5 优质）×2 + `authority`（0—4）作为粗排权重。

任务归属：`web.request()` 要往事件表记账，`invoke_agent()` 要读任务状态，首页模块没有用户任务，
故就地复用一条固定 id 的宿主任务 `hotspot-homepage`（`metadata.homepage_module=True`）。
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, get_args

from core import historical_web as web
from pydantic import BaseModel, HttpUrl, ValidationError

from .config import MODEL_NAME, search_endpoint
from .model_client import invoke_agent
from .tool_executor import RunContext

# 类别枚举只有一个家：`CATEGORIES` 由类型注解推导，不写第二份字面量。
Category = Literal['社会民生', '治安', '文化旅游', '执政形象', '医疗卫生', '经济', '国际']
CATEGORIES = get_args(Category)

# 固定查询集：**换口径只改这里**（多/少一条查询就多/少一轮搜索，web_usage 事件与成本随之变化）。
# `{since}` = today-3 天的 ISO 日期，用搜索语法 `after:` 锁窗口，比让模型判断「最近三天」可靠。
CATEGORY_QUERIES = {
    '社会民生': '民生 新闻 事件 after:{since}',
    '治安': '案件 公安 通报 after:{since}',
    '文化旅游': '文旅 景区 新闻 after:{since}',
    '执政形象': '干部 被查 通报 作风 after:{since}',
    '医疗卫生': '医院 医疗 药品 新闻 after:{since}',
    '经济': '经济 政策 发布 产业 after:{since}',
    '国际': '国际 涉华 影响中国 after:{since}',
}
# 某类别达标不足时改用更宽的查询重试一次（实测「经济」「国际」长期偏少）。
BROADER_QUERIES = {
    '经济': '经济 消费 就业 产业 政策',
    '国际': '国际 外交 涉华 全球',
}
CATEGORY_MIN = 3             # 达标条数低于此值即视为该类别偏少
RESULTS_PER_QUERY = 20       # 官方 count 上限 50；20 条/类实测足够
MAX_SEARCH_RESULTS = 80      # 喂给模型的候选上限（控 token）
RERANK_FLOOR = 1.5           # rerank_score ≥1.5 为优质，低于此值丢弃
TITLE_JACCARD = 0.6          # 标题相似度 ≥0.6 视为同一事件（繁简/节目名/多来源变体）
SUMMARY_FEED_CHARS = 220     # 喂模型的摘要截断长度
SEARCH_QUERY_MAX = 128       # 接口硬限制：query 超过 128 字符直接 HTTP 400（不静默截断）
# 只用**负向排除**，绝不用 `site:` 白名单：实测白名单会把真实治安/民生热点滤成政策通稿
# （治安类别达标 0 条、经济类别直接 400）。这里只放确定是镜像/垃圾的站点。
EXCLUDE_SITES = ('big5.cctv.com',)
BAD_TITLE_MARKERS = ('第A1版', 'A1版', '晨会纪要', '周报', '今日头版', '安全验证',
                     '新聞聯播', '午夜新闻', '朝闻天下', '新闻直播间')

ITEM_COUNT = 20
WINDOW_DAYS = 3
KIND = 'hotspot_digest'
OWNER_TASK = 'hotspot-homepage'
MODEL_ADAPTER = None  # 测试/宿主可替换的模型适配器（None = 走真实模型）


class HotspotItem(BaseModel):
    rank: int
    title: str
    summary: str
    category: Category
    url: HttpUrl | str
    source: str = ''


class HotspotDigest(BaseModel):
    items: list[HotspotItem]


class HotspotError(Exception):
    """首页热点模块的统一错误：`code` 直接作为 API 错误码，`status` 直接作为 HTTP 状态。"""

    code = 'hotspot_error'
    status = 502


class HotspotSearchNotConfigured(HotspotError):
    code = 'search_not_configured'
    status = 409


class HotspotSchemaInvalid(HotspotError):
    code = 'hotspot_schema_invalid'
    status = 502


class HotspotUrlNotFromSearch(HotspotError):
    """编造闸门：模型引用了候选集里不存在的链接。"""

    code = 'hotspot_url_not_from_search'
    status = 502


class HotspotItemsIncomplete(HotspotError):
    """去重后不足 20 条（同一链接被重复使用也算不足）。"""

    code = 'hotspot_items_incomplete'
    status = 502


class HotspotSearchFailed(HotspotError):
    code = 'hotspot_search_failed'
    status = 502


class HotspotSearchQueryTooLong(HotspotError):
    """接口硬限制：`query` 超过 128 字符会被 HTTP 400 拒绝（不静默截断，截断会改语义）。"""

    code = 'search_query_too_long'
    status = 502


class HotspotModelFailed(HotspotError):
    code = 'hotspot_model_failed'
    status = 502


def window_for(today: date) -> dict[str, str]:
    """采集窗口：`from` = today-3 天，`to` = today（两端都是 ISO 日期）。"""
    return {'from': (today - timedelta(days=WINDOW_DAYS)).isoformat(), 'to': today.isoformat()}


def _url_key(url: str) -> str:
    """URL 归并口径（候选集内部去重）：去空白、去尾部斜杠。"""
    return (url or '').strip().rstrip('/')


def _identity(url: str) -> tuple[str, str, str]:
    """链接身份 = (scheme, host, path)。

    为什么比较时忽略查询串：实测模型会**逐字照抄但改写追踪参数**（把
    `scm=...-0-0-0-0.5_1334` 抄成 `...-1-0-0-0.5_1334`），这类一位之差的查询串不影响文章
    身份，却足以让严格全串匹配误杀。故身份判定只看 host+path；**落库的 url 一律替换回
    候选集里的原文**，所以前端永远指向搜索实际返回的链接，不存在「模型自己拼的链接」。
    """
    from urllib.parse import urlsplit

    parts = urlsplit((url or '').strip())
    return (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip('/'))


def _stamp(value) -> datetime | None:
    """日期字段（UTC RFC3339，可能为 null）→ 带时区的 datetime；不可解析返回 None。"""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _in_window(value, window: dict) -> bool | None:
    """True/False = 明确在/不在窗口内；None = 日期未知（保留但排序靠后）。"""
    stamp = _stamp(value)
    if stamp is None:
        return None
    start = datetime.fromisoformat(window['from'] + 'T00:00:00+00:00')
    end = datetime.fromisoformat(window['to'] + 'T23:59:59+00:00')
    return start <= stamp <= end


def _weight(entry: dict) -> float:
    """客观权重：`rerank_score × 2 + authority`（不依赖模型的印象分）。"""
    score = entry.get('rerank_score')
    authority = entry.get('authority')
    return (float(score) if isinstance(score, (int, float)) else 0.0) * 2 + \
           (float(authority) if isinstance(authority, (int, float)) else 0.0)


def _host(url: str) -> str:
    from urllib.parse import urlparse

    return (urlparse(url).hostname or '').lower()


def _excluded(url: str) -> bool:
    host = _host(url)
    return any(host == site or host.endswith('.' + site) for site in EXCLUDE_SITES)


def _tokens(title: str) -> set[str]:
    from core.text import tokenize

    return set(tokenize(title or ''))


def _same_event(left: set[str], right: set[str]) -> bool:
    if not left or not right:
        return False
    union = len(left | right)
    return bool(union) and len(left & right) / union >= TITLE_JACCARD


def _candidate(row: dict, category: str, window: dict) -> dict | None:
    """结果级过滤：坏标题 / 低分 / 非 http(s) / 排除站点 / 日期明确在窗口外 → None。"""
    title = str(row.get('title') or '').strip()
    url = str(row.get('url') or '').strip()
    if not title or not url.startswith(('http://', 'https://')):
        return None
    if any(marker in title for marker in BAD_TITLE_MARKERS):
        return None
    if _excluded(url):  # 与查询侧的 `-site:` 双保险
        return None
    score = row.get('rerank_score')
    if isinstance(score, (int, float)) and score < RERANK_FLOOR:
        return None
    if _in_window(row.get('date'), window) is False:
        return None
    return {'category': category, 'title': title, 'url': url,
            'summary': str(row.get('summary') or row.get('snippet') or '').strip(),
            'snippet': str(row.get('snippet') or '').strip(),
            'source': str(row.get('site_name') or '').strip(),
            'date': row.get('date'), 'rerank_score': score,
            'authority': row.get('authority')}


def build_query(base: str, since: str) -> str:
    """查询串 = 基础查询 + `after:<since>` + 逐条 `-site:<排除站>`；超 128 字符报错不截断。"""
    query = f'{base} after:{since}' + ''.join(f' -site:{site}' for site in EXCLUDE_SITES)
    if len(query) > SEARCH_QUERY_MAX:
        raise HotspotSearchQueryTooLong(
            f'search_query_too_long:{len(query)}>{SEARCH_QUERY_MAX}')
    return query


def _query(context, query: str, failures: list[dict]) -> list[dict]:
    try:
        data = web.request('search', {'query': query, 'count': RESULTS_PER_QUERY,
                                      'need_content': False}, context)
    except HotspotError:
        raise
    except Exception as exc:  # 单条查询失败不拖垮整轮；失败原因随 artifact 一起留痕
        failures.append({'query': query, 'error': str(exc)[:160]})
        return []
    return [row for row in (data or {}).get('results') or [] if isinstance(row, dict)]


def _accept_title(pool: dict, tokens: dict, entry: dict) -> None:
    """事件级去重：同 URL 只留最先出现的；标题相似则留权重更高的那条。"""
    key = _url_key(entry['url'])
    if key in pool:
        return
    entry_tokens = _tokens(entry['title'])
    for other_key, other in list(pool.items()):
        if _same_event(entry_tokens, tokens[other_key]):
            if _weight(entry) > _weight(other):
                del pool[other_key]
                del tokens[other_key]
                pool[key] = entry
                tokens[key] = entry_tokens
            return
    pool[key] = entry
    tokens[key] = entry_tokens


def gather(context, window: dict) -> tuple[list[dict], dict, dict, list[dict]]:
    """① 按类别查 ② 两级过滤 + 事件级去重；返回 (候选, 链接白名单, 类别短缺, 查询失败)。"""
    since = window['from']
    pool: dict[str, dict] = {}
    tokens: dict[str, set[str]] = {}
    shortage: dict[str, int] = {}
    failures: list[dict] = []
    for category, template in CATEGORY_QUERIES.items():
        accepted = [entry for entry in (_candidate(row, category, window)
                                        for row in _query(context, build_query(template.split(' after:')[0], since), failures))
                    if entry]
        if len(accepted) < CATEGORY_MIN and category in BROADER_QUERIES:
            accepted += [entry for entry in (_candidate(row, category, window)
                                             for row in _query(context, build_query(BROADER_QUERIES[category], since), failures))
                         if entry]
        if len(accepted) < CATEGORY_MIN:
            shortage[category] = len(accepted)
        for entry in accepted:
            _accept_title(pool, tokens, entry)
    # 排序口径：`rerank_score*2+authority` 降序为主，`date` 新的优先做 tie-break（date 为 null 排在同权重之后）。
    ordered = sorted(pool.values(),
                     key=lambda entry: (_weight(entry),
                                        _stamp(entry.get('date')) or datetime.min.replace(tzinfo=timezone.utc)),
                     reverse=True)
    candidates = ordered[:MAX_SEARCH_RESULTS]
    # 白名单：链接身份 → 候选集原文 url（同一 host+path 只留最先出现的原文）
    allowed: dict[tuple[str, str, str], str] = {}
    for entry in candidates:
        allowed.setdefault(_identity(entry['url']), entry['url'])
    return candidates, allowed, shortage, failures


def validate_digest(payload) -> list[dict]:
    """结构闸门：恰好 20 条 / 7 类枚举 / http(s) / 标题摘要非空。不合格抛 `hotspot_schema_invalid`。"""
    try:
        digest = HotspotDigest.model_validate(payload)
    except ValidationError as exc:
        raise HotspotSchemaInvalid('hotspot_schema_invalid:' + str(exc).splitlines()[0][:200]) from exc
    problems: list[str] = []
    if len(digest.items) != ITEM_COUNT:
        problems.append(f'items={len(digest.items)}')
    items = []
    for position, item in enumerate(digest.items, 1):
        url = str(item.url)
        if not url.startswith(('http://', 'https://')):
            problems.append(f'rank{item.rank}:url')
        if not item.title.strip():
            problems.append(f'rank{item.rank}:title')
        if not item.summary.strip():
            problems.append(f'rank{item.rank}:summary')
        if item.category not in CATEGORIES:
            problems.append(f'rank{item.rank}:category={item.category}')
        items.append({'rank': item.rank if item.rank else position, 'title': item.title.strip(),
                      'summary': item.summary.strip(), 'category': item.category,
                      'url': url, 'source': (item.source or '').strip()})
    if problems:
        raise HotspotSchemaInvalid('hotspot_schema_invalid:' + ','.join(problems[:8]))
    return items


def validate_urls(items: list[dict], allowed: dict) -> list[dict]:
    """编造闸门：每条 url 必须命中候选集（host+path）；命中则**把 url 换回候选原文**。

    任何不在候选集里的链接 → `hotspot_url_not_from_search`（伪造数据不落库）。
    """
    forged = []
    canonical_items = []
    for item in items:
        canonical = allowed.get(_identity(item['url']))
        if canonical is None:
            forged.append(item['url'])
            canonical_items.append(item)
        else:
            canonical_items.append({**item, 'url': canonical})
    if forged:
        raise HotspotUrlNotFromSearch('hotspot_url_not_from_search:' + ','.join(forged[:3]))
    return canonical_items


def validate_complete(items: list[dict]) -> None:
    """去重后必须满 20 条（同一链接重复使用 = 凑数）。"""
    if len({_url_key(item['url']) for item in items}) < ITEM_COUNT:
        raise HotspotItemsIncomplete('hotspot_items_incomplete:distinct_urls<20')


def _index_path(store) -> Path:
    return Path(store.root) / 'hotspot' / 'latest.json'


def _write_index(store, ref: str, data: dict) -> None:
    """「最近一次」指针：artifact 内容是哈希寻址的，只有指针文件能回答「哪一次是最新」。"""
    path = _index_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({'ref': ref, 'collected_at': data['collected_at'],
                          'window': data['window']}, ensure_ascii=False).encode()
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def latest(store) -> dict | None:
    """读最近一次已落库的 digest；没有（或指针损坏）返回 None。**不触发采集、不读模型。**"""
    path = _index_path(store)
    if not path.is_file():
        return None
    try:
        index = json.loads(path.read_text(encoding='utf-8'))
        data = store.get_artifact(index['ref'])
    except (OSError, ValueError, KeyError):
        return None
    return {**data, 'ref': index['ref'], 'available': True}


def view(store, today: date | None = None) -> dict:
    """`GET /api/hotspot`：只读缓存。无缓存时给空态 + 窗口，绝不触发采集。"""
    cached = latest(store)
    if cached is not None:
        return {'available': True, 'window': cached['window'],
                'collected_at': cached['collected_at'], 'items': cached['items'],
                'model': cached.get('model', ''), 'ref': cached['ref'],
                'search_configured': cached.get('search_configured', True)}
    return {'available': False, 'window': window_for(today or date.today()), 'items': []}


def ensure_task(store):
    """宿主任务：工件归属 + `web.request()` / `invoke_agent()` 的记账对象。"""
    from .schemas import TaskState

    try:
        return store.get_task(OWNER_TASK)
    except KeyError:
        state = TaskState(id=OWNER_TASK, kind='report', phase='writing',
                          metadata={'homepage_module': True,
                                    'label': '首页 · 今日热点话题采集'})
        return store.put_task(state)


def _result_lines(candidates: list[dict]) -> list[str]:
    """候选集的紧凑格式（每条一行，控 token）：`[n] 类别 | 标题 | 摘要 | LINK: url`。"""
    lines = []
    for index, row in enumerate(candidates, 1):
        summary = row['summary'].replace('\n', ' ')[:SUMMARY_FEED_CHARS]
        lines.append(f"[{index}] {row['category']} | {row['title']} | {summary} | LINK: {row['url']}")
    return lines


def _payload(today: date, window: dict, lines: list[str], errors: list[str]) -> dict:
    from .agent import get_prompt

    payload = {'instruction': get_prompt('hotspot_collector.collect'),
               'today': today.isoformat(), 'window': window, 'item_count': ITEM_COUNT,
               'categories': list(CATEGORIES), 'must_search_online': True,
               'search_result_count': len(lines), 'search_results': lines,
               'notes': ('候选集已按 rerank_score×2+authority 粗排，类别由查询来源预标注（可微调但倾向保留）。'
                         '只从 search_results 里挑 20 条；每条 url 必须原样照抄某一条的 LINK，'
                         '不许新增、改写、拼接链接；不输出分析与评论，只输出 JSON。')}
    if errors:
        payload['correction_errors'] = errors
    return payload


async def collect(store, *, model_adapter=None, today: date | None = None,
                  now: datetime | None = None) -> dict:
    """`POST /api/hotspot/collect`：查搜索凭据 → 查+筛+去重 → 单次结构化 → 三道闸门 → 落库。"""
    # 1) 搜索凭据先于一切：未配置就结束，不建任务、不搜索、不调模型、不落 artifact。
    try:
        search_endpoint()
    except ValueError as exc:
        raise HotspotSearchNotConfigured('search_not_configured') from exc
    moment = now or datetime.now(timezone.utc)
    # 窗口日期取**本地日期**，不取 moment 的 UTC 日期：本地部署在 UTC+8，
    # 每日 00:00–08:00 期间 UTC 日期比本地少一天，会让最近 3 天窗口整体前移一天，
    # 当天的要闻搜不到。collected_at 仍是 UTC 时间戳（前端 new Date() 自动转本地显示）。
    today = today or date.today()
    window = window_for(today)
    collected_at = moment.isoformat()
    adapter = model_adapter if model_adapter is not None else MODEL_ADAPTER
    context = RunContext(store, ensure_task(store).id, phase='writing', model_adapter=adapter)

    # 2) 固定类别查询集 + 两级过滤 + 事件级去重（每次 request('search', …) 自动记 web_usage）
    candidates, allowed, shortage, failures = gather(context, window)
    if not candidates:
        raise HotspotSearchFailed('hotspot_search_failed:no_results')
    lines = _result_lines(candidates)

    # 3) 单次结构化调用（不带 tools）+ 4) 三道闸门；只有 URL 编造 / 结构不合格 / 不足 20 条才重试 1 次
    errors: list[str] = []
    rejected: HotspotError | None = None
    for _attempt in range(2):
        try:
            answer = await invoke_agent('hotspot_collector', _payload(today, window, lines, errors),
                                        HotspotDigest, context,
                                        response_schema=HotspotDigest.model_json_schema())
        except ValidationError as exc:
            rejected = HotspotSchemaInvalid('hotspot_schema_invalid:' + str(exc).splitlines()[0][:200])
            errors = [f'上一次输出结构不合格：{rejected}']
            continue
        except HotspotError:
            raise
        except Exception as exc:  # 模型不可用 / 网络：502，且不落任何残缺数据
            raise HotspotModelFailed('hotspot_model_failed:' + type(exc).__name__) from exc
        try:
            items = validate_digest(answer.model_dump())
            items = validate_urls(items, allowed)
            validate_complete(items)
        except HotspotUrlNotFromSearch as exc:
            rejected = exc
            errors = ['你引用了不在候选集里的链接（编造的链接一律退回）。只能原样照抄给定 LINK：'
                      + str(exc)[:200]]
            continue
        except HotspotError as exc:
            rejected = exc
            errors = [f'上一次输出不合格：{str(exc)[:200]}'
                      '（条数=20、7 类枚举、链接格式、20 个互不相同的候选链接都会被退回）']
            continue
        data = {'window': window, 'collected_at': collected_at, 'items': items,
                'model': MODEL_NAME, 'search_configured': True,
                'category_shortage': shortage}
        ref = store.put_artifact(OWNER_TASK, KIND, data)
        _write_index(store, ref, data)
        store.append_event(OWNER_TASK, {'type': 'hotspot_digest_collected', 'ref': ref,
                                        'item_count': len(items), 'window': window,
                                        'search_queries': len(CATEGORY_QUERIES),
                                        'search_failures': failures,
                                        'category_shortage': shortage,
                                        'model': MODEL_NAME, 'search_configured': True,
                                        'url_whitelist_size': len(allowed)})
        return {**data, 'ref': ref, 'available': True}
    raise rejected or HotspotSchemaInvalid('hotspot_schema_invalid:retry_exhausted')
