"""Prompt compatibility records; absence of evidence is never treated as compatibility."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from core.packages import load_package


def bundle_digest(bundle):
    keys = ('prompts', 'roles', 'report_profiles', 'default_profile', 'template_policy')
    raw = json.dumps({k: bundle.get(k) for k in keys}, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def package_digest(package):
    digest=bundle_digest(package.prompt_bundle)
    path=package.directory/'writing_contracts.yaml'
    if path.exists():digest=hashlib.sha256(digest.encode()+b'\0'+path.read_bytes()).hexdigest()
    return digest


def prompt_status(package, templates):
    loaded = load_package(package)
    directory = loaded.directory / 'prompts'
    digest = package_digest(loaded)
    record = {}
    error = None
    try:
        path = directory / 'adaptation.json'
        if path.exists():
            record = json.loads(path.read_text(encoding='utf-8'))
            if (not isinstance(record, dict) or record.get('schema_version') != 1
                    or not isinstance(record.get('templates', []), list)
                    or any(not isinstance(x, dict) for x in record.get('templates', []))):
                raise ValueError('invalid adaptation record')
    except (OSError, ValueError, TypeError) as exc:
        error = str(exc)
        record = {}
    entries = {x.get('template_ref'): x for x in record.get('templates', [])}
    # A package has one active prompt bundle version. The most recent confirmed
    # template recorded against the current digest is the only template that is
    # considered adapted; every other confirmed template needs rematching.
    active_ref = None
    active_at = None
    for ref, entry in entries.items():
        if entry.get('status') != 'adapted' or entry.get('bundle_digest') != digest or not entry.get('adapted_at'):
            continue
        try:
            stamp = datetime.fromisoformat(str(entry['adapted_at']).replace('Z', '+00:00'))
        except ValueError:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        if active_at is None or stamp > active_at:
            active_ref, active_at = ref, stamp
    items = []
    for template in templates:
        if template.get('status') not in ('confirmed_by_human', 'confirmed'):
            continue
        entry = entries.get(template['id'], {})
        status = 'adapted' if template['id'] == active_ref else 'needs_rematch'
        items.append({'template_ref': template['id'], 'name': template.get('name', template['id']),
                      'status': status, 'adapted_at': entry.get('adapted_at') if status == 'adapted' else None,
                      'note': entry.get('note', '') if status == 'needs_rematch' else ''})
    files = [p for p in directory.rglob('*') if p.is_file() and p.name != 'adaptation.json']
    updated = max((p.stat().st_mtime for p in files), default=None)
    return {'package': package, 'bundle_digest': digest,
            'generated_at': record.get('generated_at') if record.get('bundle_digest') == digest else None,
            'files_updated_at': datetime.fromtimestamp(updated, timezone.utc).isoformat() if updated else None,
            'record_error': error, 'templates': items}
