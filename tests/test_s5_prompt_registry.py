"""WP-S5-B：`core/prompts/` 注册表与 `packages/anshun_monthly/prompts/` 数据落地用例（任务分解-S5 §4 WP-S5-B）。"""
import ast
import re
from pathlib import Path

import pytest

from app.config import PACKAGE_DIR
from core.prompts import registry

PROMPTS_DIR = PACKAGE_DIR / 'prompts'
CORE_PROMPTS_DIR = Path(__file__).resolve().parents[1] / 'core' / 'prompts'

# 键序即契约：与 app/agent.py:122-161 的声明序逐字一致（§0.3.1）
PROMPT_KEYS = (
    'style.application', 'format_reviewer.review', 'content_reviewer.review', 'writer.revise',
    'historical_researcher.plan', 'historical_researcher.research',
    'historical_researcher.page_note', 'historical_researcher.current_note',
    'writer.analysis', 'writer.outlook', 'template_analyst.template', 'writer.general',
    'writer.source_binding', 'writer.reference_repair', 'writer.analysis_output',
    'writer.outlook_field', 'writer.data_planner', 'writer.slot.base', 'writer.slot.themes',
    'writer.slot.narrative', 'writer.slot.titles', 'event_judge.top10',
    'event_classifier.classify', 'event_summarizer.summary', 'event_judge.pairs',
    'event_judge.repair', 'template_analyst.batch', 'template_analyst.repair',
    'data_processor.next_tool', 'template_analyst.charts', 'template_analyst.advice',
    'model.json_output', 'model.tool_budget_exhausted',
)

# 角色序即 roles.yaml 声明序（§0.3.3）
ROLE_KEYS = (
    'historical_researcher', 'writer_data_planner', 'event_judge', 'event_classifier',
    'event_summarizer', 'template_analyst', 'data_processor', 'writer',
    'format_reviewer', 'content_reviewer',
)

POLICY_KEYS = ('fixed_text', 'semantic_units', 'recommendations', 'top10',
               'review_controls', 'question_policy')

# 本包不接线（app/__init__.py 未 configure 提示词），测试自己注入唯一入口
registry.configure(PACKAGE_DIR)


def test_prompt_keys_and_order():
    assert list(registry.prompts()) == list(PROMPT_KEYS)


def test_prompt_values_are_str_and_nonempty():
    prompts = registry.prompts()
    assert len(prompts) == 33
    assert all(isinstance(value, str) and value for value in prompts.values())


def test_roles_shape_and_order():
    roles = registry.roles()
    assert list(roles) == list(ROLE_KEYS)
    for role_id, spec in roles.items():
        assert set(spec) == {'responsibility', 'boundary', 'output'}, role_id
        assert all(isinstance(value, str) and value for value in spec.values()), role_id


def test_template_policy_types_and_order():
    policy = registry.template_policy()
    # 四层键序逐项钉死（G-PROMPTS-ORDER 的可读版本）
    assert list(policy) == list(POLICY_KEYS)
    assert list(policy['recommendations']) == ['min_items', 'max_items', 'structure']
    assert list(policy['top10']) == ['scope', 'unit', 'ranking',
                                     'summary_min_chars', 'summary_max_chars']
    assert list(policy['review_controls']) == ['first_warning_scope']
    recommendations, top10 = policy['recommendations'], policy['top10']
    assert type(recommendations['min_items']) is int and recommendations['min_items'] == 4
    assert type(recommendations['max_items']) is int and recommendations['max_items'] == 5
    assert type(top10['summary_min_chars']) is int and top10['summary_min_chars'] == 15
    assert type(top10['summary_max_chars']) is int and top10['summary_max_chars'] == 35
    assert isinstance(recommendations['structure'], str)


def test_profiles_and_default():
    profiles = registry.report_profiles()
    assert profiles == {'anshun_monthly': {}}
    assert type(profiles['anshun_monthly']) is dict      # 空 dict 不许降级成 None（H9）
    assert registry.default_profile() == 'anshun_monthly'


def test_no_prompt_ends_with_newline():
    # 让「文件正文 = 提示词 + 恰好一个结尾 LF」的剥一规则无歧义（§3.1 H1）
    prompts = registry.prompts()
    assert [key for key, value in prompts.items() if value.endswith('\n')] == []


def test_prompt_shape_oddities():
    prompts = registry.prompts()
    assert prompts['writer.analysis_output'].startswith('\n')
    assert prompts['template_analyst.charts'].startswith('\n')
    assert prompts['event_judge.repair'][0] == ' '
    for key in ('writer.analysis_output', 'template_analyst.charts', 'event_judge.repair'):
        assert prompts[key] != prompts[key].strip(), key     # 任何 trim 都会红


def test_prompt_keys_are_path_safe():
    assert [key for key in registry.prompts() if not re.fullmatch(r'[a-z0-9_.-]+', key)] == []


def test_no_stray_prompt_files():
    on_disk = {path.stem for path in (PROMPTS_DIR / 'agent').glob('*.md')}
    assert on_disk == set(registry.prompts())


def test_unconfigured_raises():
    package_dir = registry._package_dir
    try:
        registry._package_dir = None
        for call in (registry.prompts, registry.roles, registry.template_policy,
                     registry.report_profiles, registry.default_profile):
            with pytest.raises(RuntimeError, match='package_not_configured'):
                call()
    finally:
        registry._package_dir = package_dir


def test_core_prompts_has_no_app_import():
    # 基座不得依赖 app/（否则 S7 第二客户包无法只增包目录）
    sources = sorted(CORE_PROMPTS_DIR.glob('*.py'))
    assert sources, '扫描面为空会让本用例空转通过'
    imported = set()
    for path in sources:
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split('.')[0])
    assert 'app' not in imported, imported
