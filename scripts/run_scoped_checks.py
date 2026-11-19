"""Explicit offline pytest launcher. Guards prevent mistakes, not an OS sandbox."""
from pathlib import Path
import json
import os
import re
import subprocess
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]


def run_scoped(nodes: list[str], run_root: Path) -> int:
    if not nodes or any(not re.fullmatch(r'tests/test_[\w]+\.py(?:::.+)?', n) for n in nodes):
        raise ValueError('explicit_test_nodes_required')
    root = Path(run_root).resolve()
    if root == REPO or REPO in root.parents:
        raise ValueError('external_temporary_run_root_required')
    root.mkdir(parents=True, exist_ok=True)
    guard = root / 'guard'
    guard.mkdir(exist_ok=True)
    (guard / 'sitecustomize.py').write_text(
        'from scoped_test_guard import install\ninstall()\n', encoding='utf-8')
    env = dict(os.environ)
    env.update(REPORT_DEMO_DATA=str(root / 'data'), REPORT_PACKAGE='anshun_monthly',
               REPORT_MODEL_URL='', REPORT_MODEL_KEY='', REPORT_MODEL_NAME='',
               REPORT_SEARCH_URL='', REPORT_SEARCH_KEY='',
               CLASSIFY_BASE_URL='', CLASSIFY_API_KEY='', CLASSIFY_PYTHON='',
               CLASSIFY_ENCODER='', CLASSIFY_HEAD='',
               PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8',
               MPLCONFIGDIR=str(root / 'mpl'), XDG_CACHE_HOME=str(root / 'cache'),
               TEMP=str(root), TMP=str(root), V5_SCOPED_ROOT=str(root),
               PYTHONPATH=os.pathsep.join((str(guard), str(REPO / 'scripts'), str(REPO))))
    argv = [sys.executable, '-B', '-m', 'pytest', '-q', '--tb=short', '-rfE',
            '-p', 'no:cacheprovider', '--basetemp=' + str(root / 'pytest'), *nodes]
    started = time.time()
    with (root / 'pytest.log').open('w', encoding='utf-8') as log:
        result = subprocess.run(argv, cwd=REPO, env=env, stdout=log,
                                stderr=subprocess.STDOUT, timeout=600)
    (root / 'run.json').write_text(json.dumps(
        {'argv': argv, 'started': started, 'seconds': time.time()-started,
         'exit_code': result.returncode}, ensure_ascii=False, indent=2), encoding='utf-8')
    return result.returncode


if __name__ == '__main__':
    root = Path(tempfile.mkdtemp(prefix='v5-scoped-'))
    print('Evidence:', root, flush=True)
    code = run_scoped(sys.argv[1:], root)
    print((root / 'pytest.log').read_text(encoding='utf-8')[-14000:])
    raise SystemExit(code)
