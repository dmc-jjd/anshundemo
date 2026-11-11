"""Read the explicitly generated reconciliation, bound to its frozen version."""
import hashlib,json
from pathlib import Path

def view(store,task_id,details=False):
    state=store.get_task(task_id);root=store.root/'reference-comparison'
    path=root/'summary.json'
    if not path.exists():raise ValueError('reference_comparison_not_available')
    summary=json.loads(path.read_text(encoding='utf-8'))
    if summary.get('task_id')!=task_id or summary.get('fact_ref')!=state.fact_ref:raise ValueError('reference_comparison_stale')
    source=Path(summary['source'])
    if not source.exists() or hashlib.sha256(source.read_bytes()).hexdigest()!=summary.get('source_sha256'):raise ValueError('reference_source_changed')
    if details:return {'summary':summary,'row_matches':json.loads((root/'reference-row-matches.json').read_text(encoding='utf-8')),
                        'uncovered_warned_groups':json.loads((root/'uncovered-warned-groups.json').read_text(encoding='utf-8'))}
    return summary
