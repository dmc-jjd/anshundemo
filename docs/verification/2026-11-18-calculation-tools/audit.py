"""Read-only confirmed-artifact audit; calculation inputs are entirely synthetic."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from core.field_calculations import load
from app.structured_writer import data_values, field_calculation_spec
from app.writing_pipeline.calculations import KNOWN
from test_extended_calculations import report

db = ROOT / 'data/packages/longchuan_yuebao/demo.sqlite3'
connection = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)
try:
    snapshots = []
    for ref in ('template_version-ca19317b6428a92e3b5e', 'template_version-e053b1277d8e9d4e4830'):
        row = connection.execute('SELECT path,hash FROM artifacts WHERE id=?', (ref,)).fetchone()
        raw = Path(row[0]).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        assert digest == row[1]
        snapshots.append({'ref': ref, 'sha256': digest, 'matches_index': True})
        if ref.startswith('template_version-ca193'):
            template = json.loads(raw)
finally:
    connection.close()

bindings = load('longchuan_yuebao')
fields = [f for f in template['fields'] if f['owner'] == 'data']
unbound = [f['id'] for f in fields if not (
    field_calculation_spec(f, 'longchuan_yuebao') or f['id'] in KNOWN or
    (f.get('binding') or {}).get('tool') in ('calculate_metrics', 'top10_events'))]
assert len(fields) == 35 and len(bindings) == 12 and not unbound
subset = {**template, 'fields': [f for f in fields if f['id'] in bindings]}
values, issues = data_values(subset, report(), package='longchuan_yuebao')
assert not issues, issues
assert len(values) == 12
result = {'package': 'longchuan_yuebao', 'artifacts': snapshots,
          'data_fields': len(fields), 'effective_binding_configurations': 35,
          'new_bindings': len(bindings), 'unbound_fields': unbound,
          'actual_confirmed_schema_synthetic_values': values,
          'scope': '12 new calculations executed against actual V3 schemas with synthetic inputs; 23 old bindings configuration-only; no business report or model call'}
out = Path(__file__).with_name('audit.json')
out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({k: v for k, v in result.items() if k != 'actual_confirmed_schema_synthetic_values'}, ensure_ascii=False, indent=2))
