#!/usr/bin/env python
"""L2 结构等价层门禁：比较两份产物的「结构」而非字节。

用法：
    python scripts/verify_structure.py compare OLD NEW [--ignore-keys ts,id,path] [--max-print 30]

支持类型：
    .json  -> 递归拍平成 path -> 值，忽略指定键后再比较
    .docx  -> 按段落抽取文本序列，比较段落顺序与内容
    .txt/.md -> 逐行比较

为什么需要这一层：
    L1（verify_snapshot.py）要求逐字节相等，但报告 docx 里含时间戳、任务 id、
    绝对路径等每次都会变的东西。L2 剥掉这些噪声，只比较"结构是否变了"。

退出码：0 等价 / 1 不等价 / 2 用法或读取错误
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

DEFAULT_IGNORE_KEYS = {"ts", "timestamp", "created_at", "updated_at", "generated_at", "duration_ms", "elapsed"}

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def flatten(obj, prefix="", ignore_keys=frozenset(), out=None):
    if out is None:
        out = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in ignore_keys:
                continue
            flatten(value, f"{prefix}.{key}" if prefix else str(key), ignore_keys, out)
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            flatten(value, f"{prefix}[{idx}]", ignore_keys, out)
    else:
        out[prefix or "<root>"] = obj
    return out


def normalize(value):
    if isinstance(value, float):
        # 浮点比较留一档容差，避免 0.1+0.2 这类噪声
        return round(value, 9)
    return value


def read_json_structure(path: Path, ignore_keys) -> dict:
    # utf-8-sig：Windows 侧工具（PowerShell Set-Content 等）常用带 BOM 的 UTF-8
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return {k: normalize(v) for k, v in flatten(data, ignore_keys=ignore_keys).items()}


def read_docx_structure(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        with zf.open("word/document.xml") as fh:
            tree = ET.parse(fh)
    paragraphs = []
    for para in tree.iter(f"{W_NS}p"):
        texts = [(node.text or "") for node in para.iter(f"{W_NS}t")]
        joined = "".join(texts).strip()
        if joined:
            paragraphs.append(joined)
    return paragraphs


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8-sig", errors="replace").splitlines()


def diff_sequences(old: list[str], new: list[str], max_print: int) -> list[str]:
    problems = []
    if len(old) != len(new):
        problems.append(f"条目数不同: old={len(old)} new={len(new)}")
    for idx, (a, b) in enumerate(zip(old, new)):
        if a != b:
            problems.append(f"[{idx}] old={a!r}\n      new={b!r}")
            if len(problems) >= max_print:
                problems.append("... 更多差异已省略")
                break
    return problems


def diff_dicts(old: dict, new: dict, max_print: int) -> list[str]:
    problems = []
    old_keys, new_keys = set(old), set(new)
    for key in sorted(new_keys - old_keys):
        problems.append(f"新增字段 {key} = {new[key]!r}")
    for key in sorted(old_keys - new_keys):
        problems.append(f"缺失字段 {key} (原值 {old[key]!r})")
    for key in sorted(old_keys & new_keys):
        if old[key] != new[key]:
            problems.append(f"值变化 {key}: {old[key]!r} -> {new[key]!r}")
    if len(problems) > max_print:
        problems = problems[:max_print] + [f"... 还有 {len(problems) - max_print} 处差异"]
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="L2 结构等价门禁")
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    parser.add_argument("--ignore-keys", default="", help="额外忽略的 JSON 键，逗号分隔")
    parser.add_argument("--ignore-key-regex", default="", help="忽略匹配该正则的路径")
    parser.add_argument("--max-print", type=int, default=30)
    args = parser.parse_args()

    for path in (args.old, args.new):
        if not path.exists():
            print(f"[error] 文件不存在: {path}", file=sys.stderr)
            return 2

    suffix = args.old.suffix.lower()
    if args.new.suffix.lower() != suffix:
        print(f"[error] 两侧类型不一致: {suffix} vs {args.new.suffix}", file=sys.stderr)
        return 2

    if suffix == ".json":
        ignore = set(DEFAULT_IGNORE_KEYS)
        ignore.update(k.strip() for k in args.ignore_keys.split(",") if k.strip())
        rx = re.compile(args.ignore_key_regex) if args.ignore_key_regex else None
        old = read_json_structure(args.old, ignore)
        new = read_json_structure(args.new, ignore)
        if rx:
            old = {k: v for k, v in old.items() if not rx.search(k)}
            new = {k: v for k, v in new.items() if not rx.search(k)}
        problems = diff_dicts(old, new, args.max_print)
    elif suffix == ".docx":
        problems = diff_sequences(read_docx_structure(args.old), read_docx_structure(args.new), args.max_print)
    else:
        problems = diff_sequences(read_lines(args.old), read_lines(args.new), args.max_print)

    if problems:
        print(f"结构不等价（{len(problems)} 处）：")
        for item in problems:
            print(f"  - {item}")
        print("\nRESULT: FAIL")
        return 1

    print("结构等价：未发现差异")
    print("\nRESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
