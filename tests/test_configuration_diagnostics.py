import json

import pytest

from core import section_policy
from core.packages import registry
from core.manifest import PackageError as ManifestError
from app.template_engine import builtin_templates
from app.export import _export_cfg


@pytest.mark.parametrize('reader', [section_policy.load, builtin_templates, _export_cfg])
def test_missing_package_is_not_optional_config(reader, tmp_path, monkeypatch):
    monkeypatch.setenv('REPORT_PACKAGES_ROOT', str(tmp_path))
    with pytest.raises(registry.PackageError, match='package_not_found'):
        reader('missing')


@pytest.mark.parametrize('reader,empty', [(section_policy.load, {}), (builtin_templates, []), (_export_cfg, {})])
def test_undeclared_optional_config_remains_empty(reader, empty, tmp_path, monkeypatch):
    package = tmp_path / 'demo'
    package.mkdir()
    (package / 'manifest.yaml').write_text('package: demo\nname: Demo\nreport_type: monthly\nversion: "1"\nprompts: prompts\ntemplate: template.json\n', encoding='utf-8')
    (package / 'template.json').write_text('{}', encoding='utf-8')
    monkeypatch.setenv('REPORT_PACKAGES_ROOT', str(tmp_path))
    assert reader('demo') == empty


@pytest.mark.parametrize('broken', ['template', 'manifest', 'section_shape'])
def test_section_policy_reports_broken_declared_configuration(tmp_path, monkeypatch, broken):
    package = tmp_path / 'demo'
    package.mkdir()
    (package / 'manifest.yaml').write_text('package: demo\nname: Demo\nreport_type: monthly\nversion: "1"\nprompts: prompts\ntemplate: template.json\n', encoding='utf-8')
    (package / 'template.json').write_text('{}', encoding='utf-8')
    if broken == 'template':
        (package / 'template.json').write_text('{bad', encoding='utf-8')
    elif broken == 'manifest':
        (package / 'manifest.yaml').write_text('package: [broken', encoding='utf-8')
    else:
        (package / 'template.json').write_text(json.dumps({'section_two': 'bad'}), encoding='utf-8')
    monkeypatch.setenv('REPORT_PACKAGES_ROOT', str(tmp_path))
    with pytest.raises((registry.PackageError, ManifestError, ValueError)):
        section_policy.load('demo')
