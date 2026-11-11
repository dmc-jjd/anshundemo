#!/usr/bin/env python
"""G-GRAPH 门禁：三个场景 x 四个分量 + 总哈希（S6 的"行为不变"判据）。

存在理由：S6 要把 `workflow.py` 的手写 StateGraph 换成读 `GraphSpec`，改完源码面目全非，
任何"文件内容对比"都不再成立；而 282 个既有用例里 report 图没有节点序断言、template 图
连拓扑断言都没有。唯一能证明"搭法换了、图行为没变"的判据是：固定输入 + 固定 mock 决策
序列 -> 比较可观测的执行轨迹（ORDER / FINISH / ARTIFACTS / CALLS）。

用法：
    python scripts/gate_graph.py --record   # 录首个基线（已存在则拒绝，除非 --force）
    python scripts/gate_graph.py --twice    # 连跑两遍 + 与基线逐分量比对
退出码：0 = 通过；1 = 与基线不符或两次不同值；2 = 用法/环境问题。

实现约束（实测出来的坑，别改）：
    * 必须是真实文件 + `__main__` guard：`app/tool_executor.py:46-47` 每个工具调用
      spawn 子进程并按 `__main__` 路径重导入；stdin 形态（`python -`）会 OSError，
      表现为 0 工件 / phase=failed，而摘要仍然"确定"。
    * 输入 xlsx 必须 freeze()：`zipfile.writestr` 用当前时间做 ZipInfo（精度 2 秒），
      跨 tick 两次运行字节不同 -> 文件 sha 变 -> 记录 id 内嵌 sha 前缀 -> 全链路漂移。
    * 每场景先断言 ROLES 序列，再比摘要：adapter 违反 `app/state.py:23-24` 的
      min_length=4 时 `run_reviewer` 会重试 3 次后降级 status='error'，退修循环压根不跑，
      而摘要依然确定——只比摘要等于给退化运行发绿灯。

**基线权威（勘误，2026-11-12 WP-S6-A 实测；下一个人必须先读这段）**

    判据只来自 `docs/team/baseline/graph-S6.json`，它**唯一**由 `--record` 生成。
    **本门禁的基线与 `docs/team/任务分解-S6.md` §1 的期望值不再对齐** —— §1 那 10 行里 6 行实测不可复现：

      * R1/R2 的 `ORDER`、`FINISH` 四行：**逐字命中**（图拓扑与节点落地顺序未变）。
      * R1/R2 的 `CALLS` 两行：命中所需的记录口径是"只记角色名"，与 §1 正文写的
        `(role, canon(payload))` 不一致。payload 是"发给模型的输入"的唯一覆盖，
        队长裁定**保留 payload、不为对齐过期值而降覆盖**，故此两行由 `--record` 重录。
      * R1/R2 的 `ARTIFACTS` 与总哈希四行：工件数与 §1 的"实测形态"一致（R1=5 / R2=3），
        但 ~50 种记录口径（ref / payload / kinds-only / 懒求值 / ensure_ascii / sort_keys /
        scrub 占位符文本 / compress_type / 含 task_id / 工件子集全枚举 …）均不可复现；
        且 `app/ core/ skills/ packages/ tests/` 自规格落盘后**无任何改动**（mtime 全量比对）。
        即：不是尺子错，是那 6 行过期。

    **结论：基线以 `--record` 为准，不要拿 §1 的旧数字判红。**

**灵敏度（防止"永远绿的废纸"）**

    四个分量各自都要**同时**满足"确定性"（同进程/跨进程同值）与"灵敏度"（定向改动后必变）。
    灵敏度由 `tests/test_s6_graph_gate.py::test_components_are_sensitive_to_targeted_change`
    逐分量证明：多一条 started 事件→ORDER 变；换一个 finished 相位→FINISH 变；
    改一个工件字段值（模型输出变化）→ARTIFACTS 变；改一次模型入参→CALLS 变，
    且每次改动**只**动目标分量、其余三个不变（隔离性证明，同时证明 scrub 没有吃掉语义）。
    因此本门禁**没有**任何分量被降级为结构指纹。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'tests'))

BASELINE = REPO / 'docs' / 'team' / 'baseline' / 'graph-S6.json'
SCRATCH = REPO / '.conda'  # 已在 .gitignore；残留是已知且可接受的（同 scripts/gate_golden.py）
SCENARIOS = ('R1', 'R2', 'R3')
COMPONENTS = ('ORDER', 'FINISH', 'ARTIFACTS', 'CALLS')

# 硬断言（不是比摘要）：来自既有用例的断言准绳，见 docs/team/任务分解-S6.md §1
EXPECTED_ROLES = {
    'R1': ['event_judge', 'event_classifier', 'event_summarizer'],
    'R2': ['format_reviewer', 'content_reviewer'],
    'R3': ['format_reviewer', 'writer', 'format_reviewer', 'content_reviewer',
           'writer', 'content_reviewer', 'format_reviewer'],
}


class GateAssertion(Exception):
    """比摘要更早、更硬的一道判据（角色序列 / 轮次）不成立。"""


# ---------- 规范化口径（四参数固定：改任一即"有意变更门禁"） ----------

_HEX32 = re.compile(r'^[0-9a-f]{32}$')
_HEX64 = re.compile(r'^[0-9a-f]{64}$')


def scrub(value):
    """递归清洗易变噪声：只把"整串恰好是 32/64 位小写 hex"换成占位符。"""
    if isinstance(value, str):
        if _HEX32.match(value):
            return '<uuid32>'
        if _HEX64.match(value):
            return '<hex64>'
        return value
    if isinstance(value, dict):
        return {key: scrub(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [scrub(item) for item in value]
    return value


def canon(value):
    return hashlib.sha256(
        json.dumps(scrub(value), ensure_ascii=False, sort_keys=True,
                   separators=(',', ':'), default=str).encode()
    ).hexdigest()


def _rezip(data, date_time):
    """逐条目重建 zip（定死时间戳）。"""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, 'w') as dst:
        for name in sorted(src.namelist()):
            info = zipfile.ZipInfo(name, date_time=date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            dst.writestr(info, src.read(name))
    return out.getvalue()


def freeze(data):
    """字节冻结输入。不冻结 = 摘要随运行时刻漂移 = 门禁永远红灯。"""
    return _rezip(data, (2020, 1, 1, 0, 0, 0))


def digests(raw):
    out = {name: canon(raw[name]) for name in COMPONENTS}
    out['TOTAL'] = canon({'nodes': raw['ORDER'], 'fins': raw['FINISH'],
                          'trace': raw['ARTIFACTS'], 'calls': raw['CALLS']})
    return out


# ---------- 观测：四个分量都是"运行期观测"，不改被测代码 ----------

def _workdir():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix='gg-', dir=str(SCRATCH)))


def _observe(store, adapter):
    """包 adapter 与 store.put_artifact 的实例属性：拿 CALLS / ARTIFACTS，不碰源码。"""
    calls, artifacts = [], []

    async def wrapped(role, payload):
        calls.append((role, canon(payload)))
        return await adapter(role, payload)

    original = store.put_artifact

    def put(task_id, kind, payload):
        ref = original(task_id, kind, payload)
        artifacts.append((kind, canon(payload)))
        return ref

    store.put_artifact = put
    return wrapped, calls, artifacts


def _collect(store, task_id, calls, artifacts):
    events = store.events(task_id)

    def graph_events(status):
        return [e for e in events if e.get('type') == 'graph_node' and e.get('status') == status]

    return {
        'ORDER': [(e['graph'], e['node']) for e in graph_events('started')],
        'FINISH': [(e['graph'], e['node'], e.get('phase'), e.get('error_type'))
                   for e in graph_events('finished')],
        'ARTIFACTS': list(artifacts),
        'CALLS': list(calls),
    }


# ---------- 三个场景 ----------

def _r1(xlsx, adapter=None):
    """REPORT：freeze(sample_xlsx()) 驱动的 fallback 全链路。"""
    from app.schemas import TaskState
    from app.storage import Store
    from app.workflow import Dependencies, run_report_graph
    from test_api_flow import analysis_adapter

    workdir = _workdir()
    try:
        path = workdir / 'sample.xlsx'
        path.write_bytes(xlsx)
        store = Store(workdir / 'store')
        store.put_task(TaskState(id='r1', kind='report', phase='queued', metadata={
            'input_path': str(path), 'sheet_index': 3, 'mode': 'fallback',
            'event_scope': 'negative_or_warning', 'event_scope_confirmed': True,
            'template_rules': {}, 'event_threshold': 0.65}))
        wrapped, calls, artifacts = _observe(store, adapter or analysis_adapter)
        asyncio.run(run_report_graph(Dependencies(store, wrapped), 'r1'))
        return _collect(store, 'r1', calls, artifacts)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _r2(adapter=None):
    """WRITING-PASS：seeded() + clean_review，review_only 单趟。"""
    from app.workflow import Dependencies, run_writing_graph
    from test_writing_graph import clean_review, seeded

    async def default_adapter(role, payload):
        return clean_review(payload)

    workdir = _workdir()
    try:
        store, _template, _state = seeded(workdir)
        wrapped, calls, artifacts = _observe(store, adapter or default_adapter)
        asyncio.run(run_writing_graph(Dependencies(store, wrapped), 'r', review_only=True))
        return _collect(store, 'r', calls, artifacts)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def r3_adapter(format_description='格式需要先修正。'):
    """逐字抄自 tests/test_writing_graph.py:143-154（只有那句 description 提到入参上）。"""
    from test_writing_graph import clean_review

    calls = []

    async def adapter(role, payload):
        calls.append(role)
        if role == 'writer':
            f = payload['editable_fields'][0]
            value = '格式已修正，相关风险可能增加。' if payload['issues'][0]['kind'] == 'format' else '格式与事实均已核验，相关风险可能增加。'
            return {'patches': [{'field_id': f['id'], 'before': f['value'], 'after': value, 'issue_ids': [payload['issues'][0]['id']], 'source_refs': f['source_refs']}]}
        answer = clean_review(payload)
        value = payload['fields'][0]['value']
        if role == 'format_reviewer' and not value.startswith('格式'):
            answer['issues'] = [{'field_id': 'w1', 'kind': 'format', 'quote': value, 'description': format_description, 'suggestion': '先完成本期格式修正。', 'action': 'revise'}]
        if role == 'content_reviewer':
            assert value.startswith('格式')
            if not value.startswith('格式与事实'): answer['issues'] = [{'field_id': 'w1', 'kind': 'fact', 'quote': value, 'description': '格式已过，事实还需修正。', 'suggestion': '按已经确认的事实修正。', 'action': 'revise'}]
        return answer

    return adapter


def _r3(adapter=None):
    """WRITING-LOOP：seeded() 不传 human=True + 上面的 adapter（格式环 -> 内容环 -> 终审格式）。"""
    from app.workflow import Dependencies, run_writing_graph
    from test_writing_graph import seeded

    workdir = _workdir()
    try:
        store, _template, _state = seeded(workdir)
        wrapped, calls, artifacts = _observe(store, adapter or r3_adapter())
        asyncio.run(run_writing_graph(Dependencies(store, wrapped), 'r', review_only=True))
        raw = _collect(store, 'r', calls, artifacts)
        # ROUND 只在这里携带、不参与摘要；断言在 run_scenario 里排在 ROLES 之后（顺序不能颠倒）。
        raw['ROUND'] = store.get_task('r').metadata['writing_review_run'].get('round')
        return raw
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def run_scenario(name, adapter=None, xlsx=None):
    """跑一个场景 -> 四个分量的原始序列。先断言 ROLES，再断言 ROUND（顺序不能颠倒）。"""
    if name == 'R1':
        from test_api_flow import sample_xlsx
        raw = _r1(freeze(sample_xlsx()) if xlsx is None else xlsx, adapter)
    elif name == 'R2':
        raw = _r2(adapter)
    elif name == 'R3':
        raw = _r3(adapter)
    else:
        raise KeyError(name)
    roles = [role for role, _ in raw['CALLS']]
    if roles != EXPECTED_ROLES[name]:
        raise GateAssertion(
            f'{name}: ROLES 序列不符\n  期望 {EXPECTED_ROLES[name]}\n  实际 {roles}')
    if name == 'R3' and raw.get('ROUND') != 3:
        raise GateAssertion(f"R3: ROUND 期望 3 实际 {raw.get('ROUND')}")
    return raw


def run_all():
    """尺子本体：{场景: {ORDER/FINISH/ARTIFACTS/CALLS/TOTAL: 哈希}}。"""
    return {name: digests(run_scenario(name)) for name in SCENARIOS}


def load_baseline():
    return json.loads(BASELINE.read_text(encoding='utf-8'))


# ---------- CLI ----------

def _print_hashes(hashes):
    for name in SCENARIOS:
        labels = COMPONENTS if name != 'R3' else ()  # R3 只打总哈希（规格的 13 行）
        for component in labels:
            print(f'G-GRAPH-{name}-{component}'.ljust(26) + hashes[name][component])
        print(f'G-GRAPH-{name}'.ljust(26) + hashes[name]['TOTAL'])


def main(argv=None):
    parser = argparse.ArgumentParser(description='G-GRAPH 门禁：三场景 x 四分量 x 连跑两次')
    parser.add_argument('--record', action='store_true', help='录制基线（已存在则拒绝，除非 --force）')
    parser.add_argument('--twice', action='store_true', help='同一进程内连跑两遍并断言同值')
    parser.add_argument('--force', action='store_true', help='允许覆盖已有基线（= 有意变更门禁）')
    args = parser.parse_args(argv)

    if args.record and BASELINE.exists() and not args.force:
        print(f'[error] 基线已存在，拒绝覆盖：{BASELINE}', file=sys.stderr)
        print('[hint] 确认要重录（有意变更门禁）再加 --force', file=sys.stderr)
        return 2

    hashes = {name: digests(run_scenario(name)) for name in SCENARIOS}
    _print_hashes(hashes)

    if args.record:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(hashes, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
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
        second = {name: digests(run_scenario(name)) for name in SCENARIOS}
        if second != hashes:
            print('DETERMINISM: FAIL (同进程两次运行不同值)')
            ok = False
        else:
            print('DETERMINISM: OK')

    first_diff = None
    for name in SCENARIOS:
        for component in COMPONENTS:
            actual, expected = hashes[name][component], baseline.get(name, {}).get(component)
            if actual != expected:
                first_diff = first_diff or f'{name}-{component}'
                print(f'G-GRAPH-{name}-{component}-MISMATCH baseline={expected} actual={actual}')
    if first_diff:
        print('FIRST-DIFF', first_diff)
        ok = False

    print('RESULT: PASS' if ok else 'RESULT: FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
