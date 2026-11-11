"""WP-S4-B：`core/skills/` 注册表与技能描述符的用例（任务分解-S4 §3 WP-S4-B）。"""
import json

import pytest

import app  # noqa: F401  （app/__init__.py 在 import 期 configure——注册表唯一的注入路径）
from app.config import PACKAGE_DIR, ROOT
from core.manifest import load_manifest
from core.skills import registry

SKILLS_DIR = ROOT / 'core' / 'skills'
STYLE_ID = 'lieflat-less-ai-tone'
FINGERPRINT = '11fb295225e5a8df37d6109c0a7c19f37efe4cf694bcee7cd0da99b4ca3d468f'


def test_use_matches_manifest():
    assert registry.use() == ('lieflat-less-ai-tone', 'source-binding')
    assert registry.use() == load_manifest(PACKAGE_DIR).skill_use


def test_resolvable_skips_code_skill():
    # source-binding 无描述符（实现在 app/source_binding.py），不许因此抛错（F4/D2）
    assert registry.resolvable() == ['lieflat-less-ai-tone']
    assert registry.style_skill() == 'lieflat-less-ai-tone'


def test_fingerprint_matches_provenance_and_current_value():
    declared = json.loads((registry.asset_dir() / 'PROJECT-PROVENANCE.json')
                          .read_text(encoding='utf-8-sig'))['sha256']
    assert registry.fingerprint() == FINGERPRINT
    assert registry.fingerprint() == declared


def test_skill_context_shape_and_rules():
    ctx = registry.skill_context()
    assert list(ctx) == ['name', 'upstream', 'commit', 'sha256', 'rules', 'semantic_criteria']
    assert ctx['name'] == 'lieflat-less-ai-tone'
    assert ctx['commit'] == '53160078a04926d98de57a233549612d1b89bdc9'
    assert ctx['sha256'] == FINGERPRINT
    assert ctx['rules'].startswith('## 改写原则')
    assert len(ctx['rules']) == 7104
    assert len(ctx['semantic_criteria']) == 3658


def test_labels_order_and_content():
    groups = registry.labels()
    assert list(groups) == ['rename', 'cohesion', 'colon', 'iso3']
    assert [len(v) for v in groups.values()] == [5, 5, 7, 6]
    assert groups['colon'][0] == '引语或人物发言'
    groups['rename'].append('x')            # 必须是副本，不许改到缓存里的描述符
    assert 'x' not in registry.labels()['rename']


def test_labels_not_in_source():
    # G-LABELS：标签只许住在描述符 JSON 里，core/skills 的 .py 不许内联（否则"外置"不可机械判定）
    sources = [(p, p.read_text(encoding='utf-8'))
               for p in sorted(SKILLS_DIR.rglob('*.py'))]
    assert sources, '扫描面为空会让本用例空转通过'
    for label in (text for group in registry.labels().values() for text in group):
        hits = [p.name for p, source in sources if label in source]
        assert hits == [], (label, hits)


def test_unconfigured_raises():
    package_dir, assets_root = registry._package_dir, registry._assets_root
    try:
        registry._package_dir = registry._assets_root = None
        registry._descriptor.cache_clear()   # 描述符有缓存，不清则 labels() 不经过 configure 检查
        for call in (registry.use, registry.resolvable, registry.labels,
                     registry.skill_context, registry.fingerprint):
            with pytest.raises(RuntimeError, match='package_not_configured'):
                call()
    finally:
        registry._package_dir, registry._assets_root = package_dir, assets_root
