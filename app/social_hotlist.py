"""首页「社媒热榜」占位模块：4 个平台恒返回空列表，等数据源接入。

数据源接入**只改 `_fetch_platform()` 一处**：`profile()` 的返回形状
（`{platform, collected_at, items}`）是前端与 API 的契约，接真实接口时不要动它，
只让 `_fetch_platform()` 返回 `{'collected_at': <ISO 时刻>, 'items': [...]}` 即可。
"""

PLATFORMS = ('weibo', 'douyin', 'toutiao', 'baidu')


def _fetch_platform(platform: str) -> dict:
    """平台数据源（待接入）。当前恒返回空：不猜、不编、不缓存假数据。"""
    return {'collected_at': None, 'items': []}


def profile(platform: str) -> dict:
    """`GET /api/social-hotlist?platform=...` 的返回体；非法平台抛 `ValueError('invalid_platform')`。"""
    if platform not in PLATFORMS:
        raise ValueError('invalid_platform')
    return {'platform': platform, **_fetch_platform(platform)}
