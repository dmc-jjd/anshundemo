from core.packages.context import ENV_PACKAGE, PackageNotSpecified, default_package
import pytest


def test_default_package_reads_env(monkeypatch):
    monkeypatch.setenv(ENV_PACKAGE, 'demo_b')
    assert default_package() == 'demo_b'


def test_default_package_requires_env(monkeypatch):
    monkeypatch.delenv(ENV_PACKAGE, raising=False)
    with pytest.raises(PackageNotSpecified, match='package_not_specified'):
        default_package()
