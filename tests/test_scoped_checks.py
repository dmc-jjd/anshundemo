"""The scoped launcher must reject broad runs and preserve Windows argv."""
import importlib.util
from pathlib import Path
import sys
import os
import subprocess

import pytest


def launcher():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'run_scoped_checks.py'
    spec = importlib.util.spec_from_file_location('scoped_launcher', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('nodes', [[], ['tests'], ['-k'], ['../test_x.py']])
def test_rejects_unspecified_or_broad_scope(nodes, tmp_path):
    with pytest.raises(ValueError, match='explicit_test_nodes_required'):
        launcher().run_scoped(nodes, tmp_path)


def test_preserves_argument_list_and_exit_code(tmp_path, monkeypatch):
    module = launcher()
    seen = []

    def run(argv, **kwargs):
        seen.append((argv, kwargs))
        return type('Result', (), {'returncode': 7})()

    monkeypatch.setattr(module.subprocess, 'run', run)
    node = 'tests/test_scoped_checks.py::test_preserves_argument_list_and_exit_code'
    assert module.run_scoped([node], tmp_path) == 7
    argv, options = seen[0]
    assert isinstance(argv, list) and argv[0] == sys.executable
    assert argv[-1] == node and options.get('shell', False) is False
    assert options['env']['REPORT_MODEL_KEY'] == ''
    assert Path(options['env']['REPORT_DEMO_DATA']).is_relative_to(tmp_path)


def test_child_inherits_guard_and_preserves_quoted_python_code(tmp_path):
    # A real child tests Windows argv transmission, not a shell or shlex approximation.
    script = '''
import asyncio, os, pathlib, socket
assert os.environ['REPORT_MODEL_KEY'] == ''
assert pathlib.Path(os.environ['REPORT_DEMO_DATA']).is_relative_to(os.environ['V5_SCOPED_ROOT'])
try:
    pathlib.Path('forbidden-scoped-write.txt').write_text('must not exist')
except PermissionError as exc:
    assert 'scoped_write_denied' in str(exc)
else:
    raise AssertionError('write guard not inherited')
try:
    socket.create_connection(('127.0.0.1', 9))
except RuntimeError as exc:
    assert 'scoped_real_network_denied' in str(exc)
else:
    raise AssertionError('network guard not inherited')
async def ipc():
    assert await asyncio.to_thread(lambda: 'quoted "value"') == 'quoted "value"'
asyncio.run(ipc())
print('guard inherited; quoted "value"')
'''
    result = subprocess.run([sys.executable, '-B', '-c', script], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, env=os.environ.copy(), timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'guard inherited; quoted "value"'
