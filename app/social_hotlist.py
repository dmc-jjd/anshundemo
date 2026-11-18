"""首页「社媒热榜」：用户截图的四平台模拟列表，等待内部数据源。

数据源接入**只改 `_fetch_platform()` 一处**：`profile()` 的返回形状
（`{platform, collected_at, items}`）是前端与 API 的契约，接真实接口时不要动它，
只让 `_fetch_platform()` 返回 `{'collected_at': <ISO 时刻>, 'items': [...]}` 即可。
"""

PLATFORMS = ('weibo', 'douyin', 'toutiao', 'baidu')


def _fetch_platform(platform: str) -> dict:
    """内部接口适配点。当前明确返回截图演示快照，不访问外网。"""
    from .social_hotlist_demo import snapshot
    return snapshot(platform)


def profile(platform: str) -> dict:
    """`GET /api/social-hotlist?platform=...` 的返回体；非法平台抛 `ValueError('invalid_platform')`。"""
    if platform not in PLATFORMS:
        raise ValueError('invalid_platform')
    return {'platform': platform, **_fetch_platform(platform)}
