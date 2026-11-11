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
    assert len(AGENT_DEFINITIONS) == 10
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
    assert prompt_fingerprint() == 'fd0ad70a94db03c77e38345c8eeac6852cd8cccb55b3b729dfc0a18eb8eb886e'
    assert prompt_fingerprint('anshun_monthly', ('historical_researcher.',)) == 'c291f21de4d17f58f5c397d30d19c300c1d3ea5d580d9b934b41b487326312b2'
    assert prompt_fingerprint('anshun_monthly', ('writer.analysis',)) == 'b20c64fcfa3d4058c14a16ec6612189cc9948d9c22d4354e65ac115801a7999f'
    assert prompt_fingerprint('anshun_monthly', ('writer.outlook', 'historical_researcher.')) == '717037b578e9eb0240d5e9773ef74639f36f0e0e955f534c8004902bab8d3196'
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
