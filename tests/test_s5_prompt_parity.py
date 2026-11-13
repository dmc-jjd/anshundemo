"""S5 薄壳出口：提示词外置后公开名、指纹表与错误语义一字未变。"""
import ast
import dataclasses
from pathlib import Path

import pytest

import app.agent as agent
import app.historical_research
import app.model_client
import app.reviewers
import app.structured_writer
import app.workflow
from app.agent import AGENT_DEFINITIONS, AGENT_PROMPTS, REPORT_PROMPT_PROFILES, AgentDefinition, get_prompt, prompt_fingerprint, prompt_profile
from app.reviewers import review_policy


def test_agent_py_is_thin_shell():
    source = Path('app/agent.py').read_text(encoding='utf-8')
    assert '安顺' not in source
    for key, value in AGENT_PROMPTS.items():
        if len(value) < 20:
            continue
        assert value not in source, key


def test_definitions_are_frozen_dataclasses():
    # 11 = 原有 10 个角色 + 首页热点采集角色 hotspot_collector（roles.yaml 末尾追加）
    assert len(AGENT_DEFINITIONS) == 11
    for role_id, definition in AGENT_DEFINITIONS.items():
        assert isinstance(definition, AgentDefinition) and dataclasses.is_dataclass(definition)
        assert definition.role_id == role_id
        assert definition.responsibility and definition.boundary and definition.output
        with pytest.raises(dataclasses.FrozenInstanceError):
            definition.responsibility = 'x'


def test_consumers_share_the_same_function_objects():
    assert app.reviewers.get_prompt is agent.get_prompt
    assert app.workflow.get_prompt is agent.get_prompt
    assert app.structured_writer.prompt_fingerprint is agent.prompt_fingerprint
    assert app.historical_research.prompt_fingerprint is agent.prompt_fingerprint
    assert app.model_client.AGENT_DEFINITIONS is agent.AGENT_DEFINITIONS


def test_prompt_fingerprint_table_unchanged():
    # S10-F 泛化勘误：为把 34 个提示词全部下沉基座，客户标识被泛化为通用措辞
    #   安顺 -> 本地区、贵州 -> 省域、黄果树 -> 具体地名、交通管理 -> 具体类目
    # 指令语义未变。曾因搬迁脚本在 Windows 上写入 CRLF 导致文本多出 \r，已修正为 LF。
    # 反证改动是外科手术式的：writer.analysis / writer.general 指纹逐字符未变。
    assert prompt_fingerprint() == 'c6ec2a534bb904b3f4b96b6102b0c5e55d139e7c9a7b0bc32b2519970c6a3521'
    assert prompt_fingerprint('anshun_monthly', ('historical_researcher.',)) == '21a9c51e6be1b910a975953b8ed0e24561f7e4a6d6f6516f91e3abdba44032c8'
    assert prompt_fingerprint('anshun_monthly', ('writer.analysis',)) == 'b20c64fcfa3d4058c14a16ec6612189cc9948d9c22d4354e65ac115801a7999f'
    assert prompt_fingerprint('anshun_monthly', ('writer.outlook', 'historical_researcher.')) == 'e9a9c80a78f3630b332535e6da76e77f66e885cffe6d4c0ba4ba2c024596f130'
    assert prompt_fingerprint('anshun_monthly', ('writer.general',)) == 'bd2cd11b8d232e52c1e229077d2b407d3fe5b425f5a1a4e1093869671de5775e'


def test_review_policy_unchanged():
    assert review_policy('anshun_monthly') == '7d8c8cb58258441760b687e7d835db450f384f063ff3f8b27beda4ca8d8a35b7'


def test_profiles_mutation_still_routes():
    REPORT_PROMPT_PROFILES['other_monthly'] = {'writer.analysis': 'X'}
    try:
        assert get_prompt('writer.analysis', 'other_monthly') == 'X'
    finally:
        REPORT_PROMPT_PROFILES.pop('other_monthly', None)


def test_error_semantics_unchanged(monkeypatch):
    with pytest.raises(KeyError, match='unknown_agent_prompt'):
        get_prompt('typo')
    with pytest.raises(ValueError, match='unknown_writer_prompt_profile'):
        prompt_profile({'writer_prompt_profile': 'typo'})
    monkeypatch.setitem(REPORT_PROMPT_PROFILES, 'blank_monthly', {'writer.general': '   '})
    with pytest.raises(ValueError, match='invalid_agent_prompt'):
        get_prompt('writer.general', 'blank_monthly')


def test_thin_shell_has_no_prompt_literals_in_app():
    for path in Path('app').glob('*.py'):
        if path.name == 'agent.py':
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value in ('instruction', 'execution_rule'):
                        assert not isinstance(value, ast.Constant), f'{path} has an inline prompt'
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id.endswith(('_PROMPT', '_INSTRUCTION')):
                pytest.fail(f'{path}:{node.lineno} reads a scattered prompt')
