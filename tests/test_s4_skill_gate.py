"""G-SKILL 尺子自身的用例：不复制 fixture 文本，直接复用它，避免两份输入漂移（任务分解-S4 §3 WP-S4-A）。"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import gate_skill  # noqa: E402  （尺子只有一把）


def baseline() -> dict:
    return json.loads(gate_skill.BASELINE.read_text(encoding="utf-8-sig"))


def test_style_detection_packet_matches_baseline():
    observed = gate_skill.run_once()
    want = baseline()
    assert observed["packet_sha256"] == want["packet_sha256"]
    assert observed["ref"] == want["ref"]
    assert observed["skill"]["sha256"] == want["skill"]["sha256"]
    assert observed["documents"] == want["documents"]
    assert observed["counts"] == want["counts"]


def test_style_detection_is_deterministic_in_process():
    first = gate_skill.run_once()["packet_sha256"]
    second = gate_skill.run_once()["packet_sha256"]
    assert first == second
