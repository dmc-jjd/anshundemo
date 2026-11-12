"""WP-S7-A：G-CORE-ISO 尺子的自检（6 个用例）。

期望值不在这里重复——尺子只有一把，基线只有一份（`core-S7-start.json`）。
本文件只证明两件事：① 尺子量真 `core/` 的结果 = 基线；② 尺子本身不会失效（负向探针）。

WP-S7-B 落地后（CORE-DEP 清零 = `core/` 按设计变动），两个基线用例的期望源改指
`core-S7-preB.json`——这是 A 包声明过的第二档，不改变判据语义。

S8 起按「每层一档」推进：每层门禁全绿后录 `core-S8-L<层>.json`，本文件指向**当前层**那一档
（现为 `core-S8-L1.json`；`core-S7-preB.json` / `core-S8-L0.json` 保留为历史档，不覆盖）。
"""

import importlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import gate_core_iso  # noqa: E402

BASELINE = REPO / "docs" / "team" / "baseline" / "core-S8-L1.json"


def _baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8-sig"))


def _write_tree(root: pathlib.Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_core_hash_matches_start_baseline() -> None:
    baseline = _baseline()
    assert gate_core_iso.tree_digest(REPO / "core", "*") == baseline["core_hash"]
    assert len(gate_core_iso.tree_hash(REPO / "core", "*")) == baseline["core_files"]


def test_core_dep_matches_start_baseline() -> None:
    baseline = _baseline()["core_dep"]
    observed = gate_core_iso.dep_sites(REPO / "core")
    assert observed == baseline["entries"]
    assert gate_core_iso.dep_counts(observed) == (baseline["sites"], baseline["files"])


def test_hash_detects_one_byte_change(tmp_path: pathlib.Path) -> None:
    files = {"x.py": "X = 1\n", "sub/y.py": "Y = 2\n"}
    _write_tree(tmp_path / "a" / "core", files)
    _write_tree(tmp_path / "b" / "core", files)
    assert (gate_core_iso.tree_digest(tmp_path / "a" / "core", "*")
            == gate_core_iso.tree_digest(tmp_path / "b" / "core", "*"))

    (tmp_path / "b" / "core" / "sub" / "y.py").write_text("Y = 3\n", encoding="utf-8")
    assert (gate_core_iso.tree_digest(tmp_path / "a" / "core", "*")
            != gate_core_iso.tree_digest(tmp_path / "b" / "core", "*"))


def test_dep_scan_detects_injected_import(tmp_path: pathlib.Path) -> None:
    _write_tree(tmp_path / "core", {"x.py": "from app.schemas import ToolResult\n"})
    observed = gate_core_iso.dep_sites(tmp_path / "core")
    assert observed == [{"file": "core/x.py", "line": 1, "module": "app.schemas"}]


def test_pycache_is_ignored(tmp_path: pathlib.Path) -> None:
    _write_tree(tmp_path / "core", {"x.py": "X = 1\n"})
    before = gate_core_iso.tree_hash(tmp_path / "core", "*")

    cache = tmp_path / "core" / "__pycache__"
    cache.mkdir()
    (cache / "x.pyc").write_bytes(b"\x00")
    assert gate_core_iso.tree_hash(tmp_path / "core", "*") == before
    assert len(gate_core_iso.tree_hash(tmp_path / "core", "*")) == 1


def test_gate_has_no_import_side_effects(capsys) -> None:
    before = set(sys.modules)
    importlib.reload(gate_core_iso)
    captured = capsys.readouterr()

    poisoned = {"app", "core"}
    added = {name for name in set(sys.modules) - before
             if name.split(".")[0] in poisoned}
    assert captured.out == "" and captured.err == ""
    assert added == set()
