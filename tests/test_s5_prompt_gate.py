"""S5-A：提示词门禁尺子本身的测试。

判据只从 `scripts/gate_prompts.py` + 基线取，**不在这里复制期望哈希**——两份判据必然漂移
（任务分解-S5 §4 WP-S5-A 步骤 3）。
"""
import importlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import gate_prompts  # noqa: E402  （尺子只有一把）


def _baseline():
    return json.loads(gate_prompts.BASELINE.read_text(encoding="utf-8-sig"))


def test_prompts_match_baseline():
    """逐项分开断言：失败时一眼看出是哪个对象/哪个指纹漂了。"""
    observed, baseline = gate_prompts.run_once(), _baseline()
    for key in gate_prompts.BUNDLE_KEYS:
        assert observed["parts"][key] == baseline["parts"][key], key
    assert observed["prompts_sha256"] == baseline["prompts_sha256"]
    for key in gate_prompts.COUNT_KEYS:
        assert observed["counts"][key] == baseline["counts"][key], key
    for key in gate_prompts.ORDER_HASH_KEYS:
        assert observed["order"][key] == baseline["order"][key], key
    for key in gate_prompts.ORDER_KEY_KEYS:
        assert observed["order"][key] == baseline["order"][key], key
    for name, _ in gate_prompts.FINGERPRINT_ARGS:
        assert observed["fingerprints"][name] == baseline["fingerprints"][name], name
    assert observed["review_policy"] == baseline["review_policy"]
    assert observed["skill_sha256"] == baseline["skill_sha256"]


def test_prompts_deterministic_in_process():
    """同进程连跑两次必须同值（基线不建立在不确定性上）。"""
    assert gate_prompts.run_once()["prompts_sha256"] == gate_prompts.run_once()["prompts_sha256"]


def _load(path):
    """S5-B 加载纪律的等价物：读字节（不翻译换行、不吃 BOM）+ 有则剥一个结尾 LF。"""
    raw = path.read_bytes().decode("utf-8")
    return raw[:-1] if raw.endswith("\n") else raw


def test_gate_rejects_corrupted_bundle(tmp_path):
    """负向探针：§0.8 四种脏文件都必须让哈希离开基线。"""
    clean, baseline = gate_prompts.bundle(), _baseline()
    assert gate_prompts.hash_bundle(clean) == baseline["prompts_sha256"]

    # 先证明读取纪律本身是忠实的，否则下面的“≠”可能只是 reader 写坏了。
    plain = tmp_path / "clean.md"
    plain.write_bytes((clean["AGENT_PROMPTS"]["writer.analysis"] + "\n").encode("utf-8"))
    assert _load(plain) == clean["AGENT_PROMPTS"]["writer.analysis"]

    probes = {
        "crlf": ("writer.analysis", lambda text: text.replace("\n", "\r\n")),
        "bom": ("writer.analysis", lambda text: "\ufeff" + text),
        "strip-leading-newline": ("writer.analysis_output", lambda text: text[1:]),
        "double-trailing-newline": ("writer.analysis", lambda text: text + "\n\n"),
    }
    for name, (key, corrupt) in probes.items():
        path = tmp_path / f"{name}.md"
        path.write_bytes((corrupt(clean["AGENT_PROMPTS"][key]) + "\n").encode("utf-8"))
        prompts = dict(clean["AGENT_PROMPTS"])
        prompts[key] = _load(path)
        assert gate_prompts.hash_bundle({**clean, "AGENT_PROMPTS": prompts}) != \
            baseline["prompts_sha256"], name


def test_gate_has_no_import_side_effects(capsys):
    """被测试 import 时不得打印、不得写基线（打印与 --record 全在 main()）。"""
    before = gate_prompts.BASELINE.read_bytes()
    importlib.reload(gate_prompts)
    assert capsys.readouterr().out == ""
    assert gate_prompts.BASELINE.read_bytes() == before
