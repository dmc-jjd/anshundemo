#!/usr/bin/env python
"""G-PROMPT-NEUTRAL 门禁：基座提示词不得含任何客户的专属词。

存在理由：
    `G-CORE-CLEAN` 只查 `core/**/*.py` 里的 5 个静态禁词；`core/prompts/base/agent/` 是
    **纯文本**，同一个词写进提示词既不会让 CORE-CLEAN 变红，也不进 CORE-DEP。
    于是「基座提示词与客户解耦」只能靠人工扫——本尺子把它变成机械判据。

判据（命中即 FAIL）——三类词的并集：
    1 `scripts/forbidden_terms.json` 的静态禁词（5 个）
    2 每个 `packages/<包>/template.json` 的 `vocabulary.localities`：
      canonical（键）+ 全部别名（值）。客户专属地名，全禁。
    3 同上 `vocabulary.cluster_terms` 的**键**（类目名）。客户业务口径的类目名，全禁。

**明确不含** `cluster_terms` 的词表成员（值）：那批词以通用中文词为主（投诉/消防/欠薪 等），
基座提示词用它们是通用语境、不是客户数据；纳入会把正常写作判成泄漏，而改提示词去躲通用词
才是真的改语义。类目名（键）与地名则不同——它们是客户业务口径的一部分，必须禁。

动态聚合的意义：加新客户时，只要地名与类目名进了它的 `template.json`，基座提示词就
不可能出现该客户的专属词——不需要回来改这个脚本。

扫描面：
    `core/prompts/base/agent/**/*.md`（34 条提示词正文）。
    不扫 `core/prompts/base/*.md`：那些是对照表与接入说明，明文引用客户词说明历史改动，
    不属于发给模型的内容。

用法：
    python scripts/gate_prompt_neutral.py                                  # 检查
    python scripts/gate_prompt_neutral.py --twice                          # 连跑两次并断言同值
    python scripts/gate_prompt_neutral.py --base <dir> --packages <dir>    # 负向探针用

输出：
    G-PROMPT-NEUTRAL  (34 files scanned, 37 terms: 5 static + 18 localities + 14 labels)
    RESULT: PASS
    命中时逐条 `HIT 文件:行  词  …上下文…`，末行 `RESULT: FAIL (n hits)`。

退出码：0 PASS；1 FAIL（含两次不同值）；2 输入缺失
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_BASE = REPO / 'core' / 'prompts' / 'base' / 'agent'
DEFAULT_PACKAGES = REPO / 'packages'
STATIC_TERMS = REPO / 'scripts' / 'forbidden_terms.json'
CONTEXT_CHARS = 48

#: 词表的三类来源。计数按此序去重：同名词归入更靠前的那一类（保证三类之和 = 词表大小）。
STATIC, LOCALITY, LABEL = 'static', 'localities', 'labels'


def static_terms(path: Path = STATIC_TERMS) -> list[str]:
    return [str(term) for term in json.loads(path.read_text(encoding='utf-8-sig'))]


def _templates(packages: Path) -> list[dict]:
    """所有可读的 `packages/*/template.json`；坏 JSON 跳过（不能让一个坏包放行全部门禁）。"""
    templates = []
    for path in sorted(packages.glob('*/template.json')):
        try:
            templates.append(json.loads(path.read_text(encoding='utf-8-sig')))
        except (OSError, json.JSONDecodeError):
            continue
    return templates


def locality_terms(packages: Path = DEFAULT_PACKAGES) -> list[str]:
    """canonical（键）+ 全部别名（值）——客户专属地名。"""
    terms: list[str] = []
    for data in _templates(packages):
        vocabulary = data.get('vocabulary') or {}
        for canonical, aliases in (vocabulary.get('localities') or {}).items():
            terms.append(str(canonical))
            terms.extend(str(alias) for alias in aliases or ())
    return terms


def label_terms(packages: Path = DEFAULT_PACKAGES) -> list[str]:
    """`cluster_terms` 的键 = 类目名；**不取其词表成员（值）**——见模块 docstring。"""
    terms: list[str] = []
    for data in _templates(packages):
        vocabulary = data.get('vocabulary') or {}
        terms.extend(str(label) for label in (vocabulary.get('cluster_terms') or {}))
    return terms


def term_table(packages: Path = DEFAULT_PACKAGES) -> dict[str, str]:
    """完整词表 `{词: 类别}`；三类按 static → localities → labels 顺序占位（先到先得）。"""
    table = {term: STATIC for term in static_terms()}
    for term in locality_terms(packages):
        table.setdefault(term, LOCALITY)
    for term in label_terms(packages):
        table.setdefault(term, LABEL)
    return table


def class_counts(terms: dict[str, str]) -> dict[str, int]:
    counts = {STATIC: 0, LOCALITY: 0, LABEL: 0}
    for category in terms.values():
        counts[category] += 1
    return counts


def prompt_files(base: Path = DEFAULT_BASE) -> list[Path]:
    return sorted(path for path in base.glob('**/*.md') if path.is_file())


def scan(terms: dict[str, str], base: Path = DEFAULT_BASE,
         repo: Path = REPO) -> list[dict]:
    """逐行扫；同一行有多个词命中时只报**最长**那个（避免 `医疗`/`医疗卫生` 重复计一次泄漏）。"""
    ordered = sorted(terms, key=len, reverse=True)
    hits: list[dict] = []
    for path in prompt_files(base):
        try:
            text = path.read_text(encoding='utf-8')
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for term in ordered:
                if term in line:
                    hits.append({
                        'file': path.relative_to(repo).as_posix()
                        if path.is_relative_to(repo) else path.as_posix(),
                        'line': number,
                        'term': term,
                        'source': terms[term],
                        'context': line.strip()[:CONTEXT_CHARS],
                    })
                    break
    return hits


def scan_digest(hits: list[dict]) -> str:
    raw = json.dumps(hits, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def counts_text(counts: dict[str, int]) -> str:
    return (f"{counts[STATIC]} static + {counts[LOCALITY]} localities "
            f"+ {counts[LABEL]} labels")


def report(terms: dict[str, str], files: list[Path], hits: list[dict]) -> int:
    print(f'G-PROMPT-NEUTRAL  ({len(files)} files scanned, {len(terms)} terms: '
          f'{counts_text(class_counts(terms))})')
    for hit in hits:
        print(f"HIT {hit['file']}:{hit['line']}  {hit['term']}  …{hit['context']}…")
    if hits:
        print(f'RESULT: FAIL ({len(hits)} hits)')
        return 1
    print('RESULT: PASS')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='基座提示词客户词中性门禁（G-PROMPT-NEUTRAL）')
    parser.add_argument('--base', default=str(DEFAULT_BASE), help='扫描目录（负向探针用）')
    parser.add_argument('--packages', default=str(DEFAULT_PACKAGES), help='客户包目录（负向探针用）')
    parser.add_argument('--twice', action='store_true', help='连跑两次并断言同值')
    args = parser.parse_args()

    base, packages = Path(args.base), Path(args.packages)
    if not base.is_dir():
        print(f'[error] 扫描目录缺失: {base}', file=sys.stderr)
        return 2
    if not packages.is_dir():
        print(f'[error] 客户包目录缺失: {packages}', file=sys.stderr)
        return 2
    if not STATIC_TERMS.is_file():
        print(f'[error] 静态禁词缺失: {STATIC_TERMS}', file=sys.stderr)
        return 2

    terms = term_table(packages)
    files = prompt_files(base)
    hits = scan(terms, base)
    code = report(terms, files, hits)

    if args.twice:
        second = scan(term_table(packages), base)
        first_digest, second_digest = scan_digest(hits), scan_digest(second)
        print(f'G-PROMPT-NEUTRAL-2ND  {second_digest}')
        if second_digest != first_digest:
            print('DETERMINISM: FAIL (同进程两次扫描不同值)')
            return 1
        print('DETERMINISM: OK')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
