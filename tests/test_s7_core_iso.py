"""WP-S7-A：G-CORE-ISO 尺子的自检（6 个用例）。

期望值不在这里重复——尺子只有一把，基线只有一份（`core-S7-start.json`）。
本文件只证明两件事：① 尺子量真 `core/` 的结果 = 基线；② 尺子本身不会失效（负向探针）。

WP-S7-B 落地后（CORE-DEP 清零 = `core/` 按设计变动），两个基线用例的期望源改指
`core-S7-preB.json`——这是 A 包声明过的第二档，不改变判据语义。

S8 起按「每层一档」推进：每层门禁全绿后录 `core-S8-L<层>.json`，本文件指向**当前层**那一档
（S10-H 起曾为 `core-S10-I.json`——该档三项收尾：`core/slot_writer.py` 删掉写死的 9 个客户
槽位 id（改由客户包 `template.json` 的 `writer_slots` 声明、`vocabulary.writer_slots()` 读取），
`core/prompts/base/agent/hotspot_collector.collect.md` 删掉两处硬编码类别清单（单一事实源 =
payload `categories`）；`core_files` 仍 92（新增门禁脚本在 `scripts/` 不入 `core/`），`core_hash`
前进；`app/reviewers.py` 与 `app/api_views/{approval,writing}.py` 改调 `writer_slot_ids()`，
`app_hash` 同步前进；`CORE-DEP` 仍 0/0。`core-S10-G.json` 及更早各档保留为历史档，不覆盖）。

S10-J 起本文件改指 `core-S10-J.json`：该档只新增 `core/tools/doc97.py`（`.doc`，Word 97-2003
读取器，dochan 可选依赖），`core_files` 93→94、`core_hash` 前进；`app/main.py` 两处上传白名单
放行 `.doc`，`app_hash` 同步前进；`CORE-DEP` 仍 0/0。`core-S10-I.json` 及更早各档保留、不覆盖。

S10-K 起本文件改指 `core-S10-K.json`：该档 `core/` 逐字节未变（`core_hash` 与 S10-J 相同、
`core_files` 仍 97、`CORE-DEP` 0/0），变化全部在 `app/`——模板字段弹窗新增「自定义字段」
（`app/template_draft.py`、`app/template_draft_api.py`），模板任务软删除（新增
`app/api_views/template_library.py`、`app/template_delete_api.py`，`app/main.py` 净减到 602 行），
故 `app_hash` 前进；`core-S10-J.json` 及更早各档保留、不覆盖。

S10-L 起本文件改指 `core-S10-L.json`：模板语义研判改成三轮（r1 初稿不判定 / r2 六条清单自审 /
r3 终审交人工），改了 `core/prompts/base/agent/` 下 template_analyst 的 batch/repair/advice 三个
提示词（故 `core_hash` 前进），以及 `app/template_execution.py`、`app/workflow.py`、
`app/template_exceptions.py`、`app/main.py`（净减至 600 行）；删除只读后审
（`app/template_advice.py`、`app/template_advice_api.py`），故 `app_hash` 前进；
`CORE-DEP` 仍 0/0。`core-S10-K.json` 及更早各档保留、不覆盖。
"""

import importlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import gate_core_iso  # noqa: E402

BASELINE = REPO / "docs" / "team" / "baseline" / "core-S10-L.json"


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
