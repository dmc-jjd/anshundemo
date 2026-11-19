"""Record reviewed prompt compatibility after prompt work; does not generate or confirm anything."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True)
    parser.add_argument('--template-id', action='append', required=True)
    parser.add_argument('--generated-at', required=True, help='Actual ISO8601 prompt generation/update time, with timezone')
    parser.add_argument('--base-url', default='http://127.0.0.1:8765')
    args = parser.parse_args()
    generated = datetime.fromisoformat(args.generated_at)
    if generated.tzinfo is None or generated > datetime.now(timezone.utc):
        parser.error('--generated-at must have a timezone and cannot be in the future')
    from core.packages import load_package
    from app.api_views.prompt_adaptation import package_digest
    request = urllib.request.Request(args.base_url.rstrip('/') + '/api/templates', headers={'X-Report-Package': args.package})
    templates = json.load(urllib.request.urlopen(request, timeout=15))
    confirmed = {t['id'] for t in templates if t.get('status') in ('confirmed_by_human', 'confirmed') and t.get('artifact_status') == 'available'}
    if set(args.template_id) - confirmed:
        parser.error('All template IDs must refer to available confirmed templates in the selected package')
    package = load_package(args.package)
    digest = package_digest(package)
    path = package.directory / 'prompts' / 'adaptation.json'
    record = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'schema_version': 1, 'templates': []}
    if record.get('schema_version') != 1 or not isinstance(record.get('templates'), list):
        parser.error('Invalid existing adaptation record; repair it first')
    adapted_at = datetime.now(timezone.utc).isoformat()
    entries = {entry['template_ref']: entry for entry in record['templates']}
    for ref in args.template_id:
        entries[ref] = {'template_ref': ref, 'status': 'adapted', 'adapted_at': adapted_at, 'bundle_digest': digest}
    record.update(generated_at=args.generated_at, bundle_digest=digest, templates=list(entries.values()))
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    temporary.replace(path)
    print(path)


if __name__ == '__main__':
    main()
