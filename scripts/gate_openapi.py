#!/usr/bin/env python
"""G-OPENAPI 门禁：钉住 `app.openapi()` 的 API 契约（当前全仓 0 处真实校验）。

存在理由：52 个路由是 FastAPI 装饰器，拆文件 / 改函数名 / 加 prefix 都会静默改
`operationId` 与 `paths`，**没有任何现有测试会红**（`operationId` 由函数名 + 路径派生）。
基线一旦录下，它同时钉住三件事：全部路由、每个路由的函数名、每个 pydantic 模型。

**勘误（2026-11-12 WP-S6-A 实测）**：`任务分解-S6.md` §1 写 `G-OPENAPI-PATHS` 期望 **52**，
实测 `len(app.openapi()['paths'])` = **49**；52 是**「方法+路径」运算数**
（`app/main.py` 的 52 个 `@app.<method>` 装饰器 = 52 个 operation），因为 3 个路径同时挂了
GET 与 POST。故本脚本分开输出两行：`-PATHS`（唯一路径，49）与 `-ROUTES`（路由运算，52）——
「52 条路由必须全在」由 `-ROUTES` + `-OPS` 承担，`-PATHS` 只报唯一路径数。

用法：
    python scripts/gate_openapi.py --record   # 录首个基线（已存在则拒绝，除非 --force）
    python scripts/gate_openapi.py --twice    # 连跑两遍 + 与基线逐项比对
退出码：0 = 通过；1 = 与基线不符或两次不同值；2 = 用法/环境问题。

口径：`canon` 与 G-GRAPH 同（ensure_ascii=False / sort_keys=True / separators=(',',':') /
default=str），但**不过 scrub**（OpenAPI 里没有 uuid，过 scrub 只会削弱灵敏度）。
判据只来自 `docs/team/baseline/openapi-S6.json`，脚本内不硬编码任何期望值。

灵敏度：摘要覆盖**整份规范化 spec**（无 scrub），任何路径 / 方法 / operationId / schema 字段
变化都会移动 `G-OPENAPI`；`G-OPENAPI-PATHS/OPS/COMPS` 三行只为归因，不承担判据。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

BASELINE = REPO / 'docs' / 'team' / 'baseline' / 'openapi-S6.json'


def canon(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True,
                   separators=(',', ':'), default=str).encode()
    ).hexdigest()


def snapshot():
    """四段快照：整份摘要 + 路径 + (方法 路径 -> operationId) + components.schemas 键。"""
    from app import main  # 延迟 import：模块导入时不触碰 app/Store

    spec = main.app.openapi()
    paths = spec.get('paths', {})
    operations = sorted(
        f'{method.upper()} {path} -> {operation.get("operationId", "")}'
        for path, methods in paths.items()
        for method, operation in methods.items()
        if isinstance(operation, dict)
    )
    return {
        'openapi': canon(spec),
        'paths': sorted(paths),
        'operations': operations,
        'components': sorted(spec.get('components', {}).get('schemas', {})),
    }


def load_baseline():
    return json.loads(BASELINE.read_text(encoding='utf-8'))


def _print_lines(snap):
    print('G-OPENAPI'.ljust(17) + snap['openapi'])
    print('G-OPENAPI-PATHS'.ljust(17) + str(len(snap['paths'])))
    print('G-OPENAPI-ROUTES'.ljust(17) + str(len(snap['operations'])))
    print('G-OPENAPI-OPS'.ljust(17) + canon(snap['operations']))
    print('G-OPENAPI-COMPS'.ljust(17) + canon(snap['components']))


def main(argv=None):
    parser = argparse.ArgumentParser(description='G-OPENAPI 门禁：app.openapi() 契约摘要')
    parser.add_argument('--record', action='store_true', help='录制基线（已存在则拒绝，除非 --force）')
    parser.add_argument('--twice', action='store_true', help='同一进程内连跑两遍并断言同值')
    parser.add_argument('--force', action='store_true', help='允许覆盖已有基线（= 有意变更门禁）')
    args = parser.parse_args(argv)

    if args.record and BASELINE.exists() and not args.force:
        print(f'[error] 基线已存在，拒绝覆盖：{BASELINE}', file=sys.stderr)
        print('[hint] 确认要重录（有意变更门禁）再加 --force', file=sys.stderr)
        return 2

    snap = snapshot()
    _print_lines(snap)

    if args.record:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(snap, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
                            encoding='utf-8')
        print('RECORDED', BASELINE.relative_to(REPO).as_posix())
        print('RESULT: PASS')
        return 0

    if not BASELINE.exists():
        print(f'[error] 缺基线：{BASELINE}（先跑 --record）', file=sys.stderr)
        return 2
    baseline = load_baseline()

    ok = True
    if args.twice:
        if snapshot() != snap:
            print('DETERMINISM: FAIL (同进程两次运行不同值)')
            ok = False
        else:
            print('DETERMINISM: OK')

    for key, label in (('openapi', 'G-OPENAPI'), ('paths', 'G-OPENAPI-PATHS'),
                       ('operations', 'G-OPENAPI-OPS'), ('components', 'G-OPENAPI-COMPS')):
        if snap[key] != baseline.get(key):
            print(f'{label}-MISMATCH baseline={baseline.get(key)} actual={snap[key]}')
            ok = False

    print('RESULT: PASS' if ok else 'RESULT: FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
