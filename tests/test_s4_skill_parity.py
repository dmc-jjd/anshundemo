"""WP-S4-C：`app/style_skill.py` 薄壳的行为等价证据（任务分解-S4 §3 WP-S4-C）。"""
import pathlib

import app  # noqa: F401  （app/__init__.py 在 import 期 configure）
import app.reviewers
import app.style_skill
from core.skills import registry

FINGERPRINT = '11fb295225e5a8df37d6109c0a7c19f37efe4cf694bcee7cd0da99b4ca3d468f'


def test_detect_style_still_lives_in_app():
    # 实现归属的可判定证据：detect_style 没被搬走，且调用方拿到的仍是同一个对象
    assert app.style_skill.detect_style.__module__ == 'app.style_skill'
    assert app.reviewers.detect_style is app.style_skill.detect_style


def test_skill_context_values_unchanged():
    ctx = app.style_skill.skill_context()
    assert ctx['sha256'] == FINGERPRINT
    assert ctx['commit'] == '53160078a04926d98de57a233549612d1b89bdc9'
    assert ctx['name'] == 'lieflat-less-ai-tone'
    assert len(ctx['rules']) == 7104
    assert len(ctx['semantic_criteria']) == 3658


def test_is_second_section_six_cases():
    is_second_section = app.style_skill.is_second_section
    assert is_second_section({'id': 'b40_analysis_paragraph', 'kind': 'text', 'display_name': 'x'}) is True
    assert is_second_section({'id': 'monthly_recommendations', 'kind': 'text', 'display_name': 'x'}) is True
    assert is_second_section({'id': 'a', 'kind': 'analysis'}) is True
    assert is_second_section({'id': 'a', 'kind': 'paragraph_list'}) is True
    assert is_second_section({'id': 'a', 'kind': 'text', 'display_name': '研判分析'}) is True
    assert is_second_section({'id': 'a', 'kind': 'text', 'display_name': '概述'}) is False


def test_policy_version_still_follows_skill_fingerprint(monkeypatch):
    # 不钉字面值（S5 外置提示词后必然变）：只证明 reviewers:42 对指纹的耦合没被这次搬迁切断
    baseline = app.reviewers.review_policy('anshun_monthly')
    monkeypatch.setattr(app.reviewers, 'skill_context', lambda: {'sha256': 'x' * 64})
    assert app.reviewers.review_policy('anshun_monthly') != baseline


def test_labels_are_data_not_code():
    assert app.style_skill.LABELS == registry.labels()
    source = pathlib.Path(app.style_skill.__file__).read_text(encoding='utf-8')
    leaked = [label for group in registry.labels().values() for label in group if label in source]
    assert leaked == [], leaked
