"""Synthetic local baseline; does not start the app or contact providers."""
import json
import math
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time


def main():
    root = Path(tempfile.mkdtemp(prefix='v5-measure-'))
    os.environ.update(REPORT_DEMO_DATA=str(root / 'data'), REPORT_MODEL_KEY='', REPORT_SEARCH_KEY='',
                      PYTHONDONTWRITEBYTECODE='1')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from core.packages import registry
    from core.storage import Store
    from core.schemas import TaskState
    os.environ['REPORT_PACKAGES_ROOT'] = str(root / 'packages')
    for name in ('demo_a', 'demo_b'):
        folder = root / 'packages' / name
        folder.mkdir(parents=True)
        (folder / 'manifest.yaml').write_text(
            f'package: {name}\nreport_type: monthly\nversion: "1"\nprompts: prompts\ntemplate: template.json\n', encoding='utf-8')
        (folder / 'template.json').write_text(json.dumps({'fields': [{'id': 'field'}] * 100}), encoding='utf-8')
    scans = {'calls': 0, 'files': 0, 'milliseconds': 0}
    tree_stamp = registry._tree_stamp
    def counted(path):
        start = time.perf_counter()
        value = tree_stamp(path)
        scans['calls'] += 1
        scans['files'] += len(value)
        scans['milliseconds'] += (time.perf_counter() - start) * 1000
        return value
    registry._tree_stamp = counted
    def measure(action):
        samples = []
        for _ in range(30):
            start = time.perf_counter()
            action()
            samples.append((time.perf_counter() - start) * 1000)
        return {'n': len(samples), 'median_ms': statistics.median(samples),
                'p95_ms': sorted(samples)[math.ceil(.95 * len(samples)) - 1]}
    def load(cold):
        if cold:registry.invalidate()
        for name in ('demo_a', 'demo_b'):
            value = registry.load(name)
            value.manifest; value.template
    results = {'root': str(root), 'synthetic': True, 'packages': 2,
               'package_cold': measure(lambda: load(True)), 'package_warm': measure(lambda: load(False))}
    results['fingerprint_scans'] = dict(scans)
    store = Store(root / 'store')
    for i in range(100):
        store.put_task(TaskState(id=str(i), kind='report', phase='queued'))
    for i in range(1000):
        store.append_event('0', {'type': 'synthetic', 'index': i})
    results['list_100_tasks'] = measure(store.list_tasks)
    results['read_1000_events'] = measure(lambda: store.events('0'))
    results['read_last_100_events'] = measure(lambda: store.events('0', limit=100))
    from app.api_views.template_library import list_templates
    from core.package_store import PackageStores
    os.environ['REPORT_PACKAGE'] = 'demo_a'
    routed = PackageStores(root / 'routed')
    store_scans = {'store_scans': 0}
    scan = routed._scan
    def counted_scan(*args, **kwargs):
        store_scans['store_scans'] += 1
        return scan(*args, **kwargs)
    routed._scan = counted_scan
    for package in ('demo_a', 'demo_b'):
        local = routed.store_for(package)
        for i in range(50):
            tid = package + str(i)
            ref = local.put_artifact(tid, 'template', {
                'status': 'confirmed_by_human', 'writer_schema': {'type': 'object'},
                'source_reports': [], 'fields': [], 'blocks': []})
            local.put_task(TaskState(id=tid, kind='template', package=package,
                                    phase='template_confirmed', metadata={'confirmed_template_ref': ref}))
    results['template_list_50_of_100'] = measure(lambda: list_templates(routed, 'demo_a'))
    results['template_list_store_scans'] = dict(store_scans)
    from core.packages.context import package_context
    with package_context('demo_a'):
        results['template_list_all_100'] = measure(lambda: list_templates(routed))
    (root / 'measurements.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
