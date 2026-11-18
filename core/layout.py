"""Package layout filenames. Directory resolution stays in core.paths.template_dir."""
from __future__ import annotations

DEFAULT_DOCX = "template-with-placeholders.docx"
DEFAULT_MANIFEST = "report.template.json"


def _cfg(package=None) -> dict:
    try:
        from core.packages import load_package
        return dict(getattr(load_package(package).manifest, "layout", None) or {})
    except Exception:
        return {}


def docx_name(package=None) -> str:
    return str(_cfg(package).get("docx") or DEFAULT_DOCX)


def manifest_name(package=None) -> str:
    return str(_cfg(package).get("manifest") or DEFAULT_MANIFEST)


def docx_path(package=None):
    from core import paths
    return paths.template_dir(package) / docx_name(package)


def manifest_path(package=None):
    from core import paths
    return paths.template_dir(package) / manifest_name(package)


def source_docx_name(package=None) -> str:
    return str(_cfg(package).get("source_docx") or "")


def source_docx_path(package=None):
    name = source_docx_name(package)
    if not name:
        return None
    from core import paths
    return paths.template_dir(package) / name


def download_name(package=None) -> str:
    cfg = _cfg(package)
    if cfg.get("download_name"):
        return str(cfg["download_name"])
    try:
        from core.packages import load_package
        report_type = load_package(package).manifest.report_type or "报告"
    except Exception:
        report_type = "报告"
    return f"{report_type}占位模板.docx"
