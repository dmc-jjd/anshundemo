"""Current-bundle corruption probes independent of the frozen S5 migration gate.

The historical baseline gate remains unchanged and can still report drift.
"""
import copy
import importlib.util
from pathlib import Path

import pytest


@pytest.mark.parametrize('damage', ['crlf', 'bom', 'leading', 'trailing'])
def test_current_prompt_bundle_detects_corruption(damage):
    path = Path(__file__).resolve().parents[1] / 'scripts/gate_prompts.py'
    spec = importlib.util.spec_from_file_location('current_prompt_probe', path)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    clean = gate.bundle()
    key = 'writer.analysis_output' if damage == 'leading' else 'writer.analysis'
    original = clean['AGENT_PROMPTS'][key]
    if damage == 'crlf':
        changed = original.replace('\n', '\r\n')
    elif damage == 'bom':
        changed = '\ufeff' + original
    elif damage == 'leading':
        assert original.startswith('\n')
        changed = original[1:]
    else:
        changed = original + '\n\n'
    corrupt = copy.deepcopy(clean)
    corrupt['AGENT_PROMPTS'][key] = changed
    assert gate.hash_bundle(clean) == gate.hash_bundle(gate.bundle())
    assert gate.hash_bundle(corrupt) != gate.hash_bundle(clean)
