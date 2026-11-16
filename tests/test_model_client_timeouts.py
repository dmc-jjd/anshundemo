"""模型请求超时预算：长任务角色 180s、其余角色 45s。

实跑背景（前序队员在生产直连上实测，非桩）：首页热点采集 `hotspot_collector` 的 13 条查询
约 30s 全部成功，随后一次结构化调用（89 条候选喂模型）在默认 45s 超时处失败
（`hotspot_model_failed:TimeoutError`，45s × 3 次重试，总 144.4s）；把该角色预算抬到 180s
后 elapsed 64.6s 成功出 30 条。故 `hotspot_collector` 必须落在 `LONG_TIMEOUT_ROLES` 里，
且默认 45s 不能被顺手抬成 180s（普通/未来角色仍走 45s）。
"""
import pathlib

import pytest

from core import model_client

#: 与源码 `LONG_TIMEOUT_ROLES` 分开写：这里断言的是「这些角色必须长预算」的契约，
#: 不跟着白名单一起改，否则删掉一个角色用例仍绿。
LONG_ROLES = (
    'template_analyst', 'writer', 'writer_data_planner', 'historical_researcher',
    'format_reviewer', 'content_reviewer',
    'event_judge', 'event_classifier', 'event_summarizer', 'data_processor',
    'hotspot_collector',
)


def test_hotspot_collector_resolves_to_at_least_180_seconds():
    """首页热点采集：45s 实测必超时，解析出的预算必须 ≥180s。"""
    assert 'hotspot_collector' in model_client.LONG_TIMEOUT_ROLES
    assert model_client.request_timeout('hotspot_collector') == 180
    assert model_client.request_timeout('hotspot_collector') >= 180


@pytest.mark.parametrize('role_id', [r for r in LONG_ROLES if r != 'hotspot_collector'])
def test_other_long_roles_stay_at_180(role_id):
    """既有长任务角色不受本次改动影响，仍是 180s。"""
    assert role_id in model_client.LONG_TIMEOUT_ROLES
    assert model_client.request_timeout(role_id) == 180


def test_unregistered_role_keeps_the_45_second_default():
    """普通/未来角色仍是默认 45s（没有被顺手抬成 180s）。"""
    assert 'locality_researcher_future' not in model_client.LONG_TIMEOUT_ROLES
    assert model_client.request_timeout('locality_researcher_future') == 45


def test_invoke_agent_passes_the_resolved_timeout_to_urlopen():
    """超时确实由 `request_timeout()` 统一解析（不是写死在调用点的三元表达式）。"""
    source = pathlib.Path(model_client.__file__).read_text(encoding='utf-8')
    assert 'timeout=request_timeout(role_id)' in source
    # 调用点不许再出现写死的 45/180 三元分支
    assert 'timeout=180 if role_id' not in source
