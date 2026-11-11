#!/usr/bin/env python
"""G-PKG-B 冒烟（P7 的行为判据）：`REPORT_PACKAGE=demo_b` 下跑 report 图 fallback 全链路到 `awaiting_review`。

存在理由：
    「只加包、不动基座」有两半证据。`G-CORE-ISO` 证明基座与宿主一字节没动（静态），本脚本证明
    换一个包之后**同一份代码真的按新包的数据跑完整链路**（行为）。缺一半就是空话：
    只有哈希相等 = 可能是包根本没被读到；只有冒烟通过 = 可能是基座被就地改了。

判据全部来自「B 的包数据 vs A 的包数据」，不来自本文件里的期望值表：
    CHARTS / PROMPTS / ROLES / LOCALITIES / STYLE_SKILL 由四个注册表**实际返回**，脚本只断言
    「与 A 不同」这一件事（B 3 张图 vs A 5 张；B 2 个专区 vs A 八区县；B 10 个提示词 vs A 32）。
    `LOCALITY_HITS 景区片区=2` 才是「数据真的换了」的行为判据——A 的八区县在同一份样本上命中 0。

三条实现约束（踩过才知道）：
    1 **必须在 `import app` 之前设 `os.environ['REPORT_PACKAGE']`**：`app/config.py:39` 在 import 期
      读环境变量并把 `PACKAGE_DIR` 固定下来，晚一步就还是 A 的包（也就是说，本脚本的 `main()`
      里对 app 的 import 必须都在 env 赋值之后）。
    2 **必须是真实文件 + `if __name__ == '__main__'`**：`app/tool_executor.py:47` 每次工具调用都
      spawn 一个子进程并按 `__main__` 路径重导入本脚本。`python -`（stdin）形态会 OSError，表现为
      0 工件 / `phase='failed'`，而摘要仍然"确定"（任务分解-S6 §0.7 F5 实测）。
    3 **输入与 adapter 逐字复制 `tests/test_api_flow.py:8-26`**，不 `import` 那个模块：它的顶层
      `import app.main` 会把 FastAPI 应用与 `Store()` 一起拉起来（写仓库 `data/`）。

用法：
    python scripts/smoke_package_b.py          # 人读：13 行固定键序
    python scripts/smoke_package_b.py --json   # 机读：末行多一行 JSON（键序同上）
退出码：0 PASS；1 第一处不符（打印 expected/got）。
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

PACKAGE = "demo_b"
SCRATCH = REPO / ".conda"  # 已 gitignore；残留是已知且可接受的（同 scripts/gate_graph.py）
TASK_ID = "pkg-b"

#: 基座 `core/charts/spec.ChartStyles` 的 5 个枚举 id（B 必须是子集，且故意只用 3 个）。
BASE_CHART_IDS = ("sentiment", "daily", "platform", "theme", "locality")
#: A 的八区县。B 的词典与它**不得相交**——相交就说明 B 读的还是 A 的数据。
A_LOCALITIES = ("西秀区", "平坝区", "普定县", "镇宁自治县", "关岭自治县",
                "紫云自治县", "黄果树旅游区", "安顺经开区")
#: `app/agent.py:28-32` 的 5 个 import 期别名 + `app/event_analysis.py` 运行期直接 get_prompt 的 5 个键。
#: 缺任何一个都会在 import 期或分析期炸（错误信息不指向"包写错"）。
REQUIRED_PROMPT_KEYS = (
    "historical_researcher.plan", "historical_researcher.research",
    "writer.analysis", "writer.outlook", "template_analyst.template",
    "event_judge.pairs", "event_judge.top10", "event_judge.repair",
    "event_classifier.classify", "event_summarizer.summary",
)
#: `app/fallback_policy.py:6` 的 13 个保底步骤 → 13 个 result_refs 键。
REQUIRED_REFS = (
    "import_records", "calculate_metrics",
    "filter_records:positive", "filter_records:neutral", "filter_records:negative",
    "filter_records:warning", "filter_records:negative_or_warning",
    "resolve_locality", "group_events", "classify_records",
    "cluster_event_themes", "discover_topics", "select_materials",
)
#: `core/tools/hints.py:19` 的 REF_ALIAS：`filter_records` scope=negative 时**额外**再写一个裸键，
#: 被 `app/workflow.py:182`（`_args_for('calculate_metrics')` 取 `r.get('filter_records')`）消费。
#: 所以实测 refs 是 16 而不是任务分解 §1.2 写的 15——那 15 漏了这个别名，它少一个就会让
#: `calculate_metrics` 的 `negative_ref` 变空。
ALIAS_REFS = ("filter_records",)
ANALYSIS_REFS = ("event_analysis", "event_analysis_checkpoint")
#: A 的 `tools.allow` 里有它、B 的没有 → B 下必被拒（"永远拒绝"型门禁的负向对照在测试里）。
REJECTED_TOOL = "build_table"
CHART_TOOLS = ("render_chart", "plot_frozen_chart")


# ---------- 夹具：逐字复制 tests/test_api_flow.py:8-26（不 import 那个模块，见 docstring 约束 3） ----------

async def analysis_adapter(role, payload):
    if role == 'event_judge' and 'events' in payload: return {'groups': [{'group_ids': [x['id']]} for x in payload['events']], 'uncertain_pairs': []}
    if role == 'event_judge': return {'items': [{'id': x['id'], 'decision': 'different', 'reason': 'synthetic test'} for x in payload['pairs']]}
    if role == 'event_classifier': return {'items': [{'id': x['id'], 'category': '其他', 'status': 'classified', 'reason': 'synthetic test'} for x in payload['events']]}
    if role == 'event_summarizer': return {'items': [{'id': x['id'], 'status': 'complete', 'summary': '来源记录反映有关问题，具体情况以原文为准。', 'source_refs': [x['evidence'][0]['ref']]} for x in payload['events']]}
    raise ValueError('unexpected role')

HEADERS = ['标题', '发布时间', '来源信息', '作者', '作者Id', '事件分类', '网址', '媒体环节', '媒体属性', '媒体级别', '舆情调性', '是否预警', '摘要']


def sample_xlsx():
    def cell(col, row, value):
        return f'<c r="{chr(65 + col)}{row}" t="inlineStr"><is><t>{value}</t></is></c>'
    rows = [HEADERS]
    for i, (title, sentiment, warning) in enumerate([('景区游客投诉排队', '负面', '已预警'), ('景区游客后续反馈', '负面', '未预警'), ('本地学校活动', '正面', '未预警'), ('社区服务消息', '中性', '未预警'), ('市场监管通报', '负面', '已预警'), ('医院服务报道', '正面', '未预警')], 2):
        rows.append([title, '2026-10-' + str(i).zfill(2), '测试来源', '', '', '', '', '网站', '其他', '其他', sentiment, warning, title])
    xml = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + ''.join(f'<row r="{i}">' + ''.join(cell(j, i, v) for j, v in enumerate(row)) + '</row>' for i, row in enumerate(rows, 1)) + '</sheetData></worksheet>'
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z: z.writestr('xl/worksheets/sheet3.xml', xml)
    return out.getvalue()


# ---------- 观测 ----------

def _workdir() -> Path:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix='pkgb-', dir=str(SCRATCH)))


def run() -> tuple[dict, list[str]]:
    """跑一次全链路并观测；返回（观测值, 问题列表）。问题列表为空才算 PASS。"""
    from app.config import PACKAGE as observed_package
    from app.schemas import TaskState, ToolCall
    from app.storage import Store
    from app.tool_executor import RunContext, execute_tool
    from app.workflow import Dependencies, run_report_graph
    from core.charts import registry as chart_registry
    from core.prompts import registry as prompt_registry
    from core.skills import registry as skill_registry
    from core.tools import vocabulary

    workdir = _workdir()
    try:
        path = workdir / 'sample.xlsx'
        path.write_bytes(sample_xlsx())
        store = Store(workdir / 'store')
        # 元数据逐字复用 scripts/gate_graph.py:192-195（R1 场景）。mode 必须是 fallback：
        # dynamic 分支在 app/workflow.py:218 读死 A 的模板路径，那样跑通的是 A 的数据。
        store.put_task(TaskState(id=TASK_ID, kind='report', phase='queued', metadata={
            'input_path': str(path), 'sheet_index': 3, 'mode': 'fallback',
            'event_scope': 'negative_or_warning', 'event_scope_confirmed': True,
            'template_rules': {}, 'event_threshold': 0.65}))
        asyncio.run(run_report_graph(Dependencies(store, analysis_adapter), TASK_ID))
        state = store.get_task(TASK_ID)
        refs = dict(state.result_refs)
        events = store.events(TASK_ID)

        def records_len(ref_key):
            return len(store.get_artifact(refs[ref_key])['records'])

        filter_counts = {
            'positive': records_len('filter_records:positive'),
            'neutral': records_len('filter_records:neutral'),
            'negative': records_len('filter_records:negative'),
            'warning': records_len('filter_records:warning'),
            'union': records_len('filter_records:negative_or_warning'),
        }
        locality_hits = Counter()
        for item in store.get_artifact(refs['resolve_locality'])['items']:
            locality_hits.update(item['candidates'])
        chart_calls = sum(1 for e in events
                          if e.get('type') == 'tool_result' and e.get('tool') in CHART_TOOLS)

        # 白名单按包生效：B 的 manifest.tools.allow 不含 build_table（A 的是含的）。
        rejected = asyncio.run(execute_tool(
            ToolCall(call_id='pkg-b-reject', tool_name=REJECTED_TOOL, arguments={},
                     reason='G-PKG-B 白名单判据'),
            RunContext(store, TASK_ID)))

        observed = {
            'PACKAGE': observed_package,
            'CHARTS': chart_registry.ids(),
            'PROMPTS': list(prompt_registry.prompts()),
            'ROLES': list(prompt_registry.roles()),
            'LOCALITIES': list(vocabulary.localities()),
            'STYLE_SKILL': skill_registry.style_skill(),
            'CHART_CALLS': chart_calls,
            'PHASE': state.phase,
            'REFS': sorted(refs),
            'FILTER_COUNTS': filter_counts,
            'LOCALITY_HITS': dict(sorted(locality_hits.items())),
            'REJECT': f'{rejected.error_code}:{REJECTED_TOOL}' if rejected.error_code else '',
        }
        return observed, _judge(observed)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _judge(o: dict) -> list[str]:
    """逐判据给出 expected/got；问题列表的第一条就是退出原因。"""
    problems: list[str] = []

    def want(label, expected, got):
        if expected != got:
            problems.append(f'{label}: expected {expected!r} got {got!r}')

    want('PACKAGE', PACKAGE, o['PACKAGE'])
    # 「不同」才是判据：id 必须是基座枚举的子集，且**恰好 3 个**（A 是 5 个）。
    want('CHARTS ⊆ 基座枚举', set(o['CHARTS']) <= set(BASE_CHART_IDS), True)
    want('CHARTS 数量（A=5）', 3, len(o['CHARTS']))
    # 10 个键 = 5 个 import 期别名 + 5 个运行期直接 get_prompt 的键（A 是 32 个）。
    want('PROMPTS 键集', set(REQUIRED_PROMPT_KEYS), set(o['PROMPTS']))
    want('ROLES', ['event_judge', 'event_classifier', 'event_summarizer'], o['ROLES'])
    # B 的两个专区与 A 的八区县不得相交（相交即说明 B 读的是 A 的数据）。
    want('LOCALITIES ∩ A 区县', [], sorted(set(o['LOCALITIES']) & set(A_LOCALITIES)))
    # report 图不渲染图表：0 才说明跑的是 fallback 数据处理链，而不是写作链。
    want('CHART_CALLS（report 图不渲染图表）', 0, o['CHART_CALLS'])
    want('PHASE', 'awaiting_review', o['PHASE'])
    want('REFS 必备 13', set(REQUIRED_REFS) - set(o['REFS']), set())
    want('REFS 别名', set(ALIAS_REFS) - set(o['REFS']), set())
    want('REFS 分析链 2', set(ANALYSIS_REFS) - set(o['REFS']), set())
    # 逐键相等而不是只数个数：多一个键就说明 fallback 链上多跑了/多写了什么。
    want('REFS 键集', set(REQUIRED_REFS) | set(ALIAS_REFS) | set(ANALYSIS_REFS), set(o['REFS']))
    # 这三个数是同一份样本的确定性统计，与包无关；它们一起变了就说明数据处理链被绕过。
    want('FILTER_COUNTS', {'positive': 2, 'neutral': 1, 'negative': 3, 'warning': 2, 'union': 3},
         o['FILTER_COUNTS'])
    # P7 的核心行为判据：B 的词典真的被读了 → 2 条命中；A 的八区县在同一份样本上命中 0。
    want('LOCALITY_HITS', {'景区片区': 2}, o['LOCALITY_HITS'])
    want('REJECT', f'tool_not_allowed:{REJECTED_TOOL}', o['REJECT'])
    return problems


def _line(label: str, value: object) -> str:
    return f'{label:<18}{value}'


def _report_lines(o: dict) -> list[str]:
    refs = o['REFS']
    return [
        _line('PACKAGE', o['PACKAGE']),
        _line('CHARTS', ','.join(o['CHARTS'])),
        _line('PROMPTS', len(o['PROMPTS'])),
        _line('ROLES', ','.join(o['ROLES'])),
        _line('LOCALITIES', ','.join(o['LOCALITIES'])),
        _line('STYLE_SKILL', o['STYLE_SKILL']),
        _line('CHART_CALLS', o['CHART_CALLS']),
        _line('PHASE', o['PHASE']),
        _line('REFS', f"{len(refs)} = 13 必备 + filter_records 别名 + event_analysis + event_analysis_checkpoint"),
        _line('FILTER_COUNTS', ' '.join(f'{k}={v}' for k, v in o['FILTER_COUNTS'].items())),
        _line('LOCALITY_HITS', ' '.join(f'{k}={v}' for k, v in o['LOCALITY_HITS'].items())),
        _line('REJECT', o['REJECT']),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description='G-PKG-B：demo_b 包 fallback 全链路冒烟')
    parser.add_argument('--json', action='store_true', help='末行多打一行 JSON（机读）')
    args = parser.parse_args()

    # 约束 1：先设环境变量，再 import app（app/config.py:39 在 import 期读它）。
    os.environ['REPORT_PACKAGE'] = PACKAGE
    observed, problems = run()

    for line in _report_lines(observed):
        print(line)
    if problems:
        for problem in problems:
            print('MISMATCH', problem)
        print(f'RESULT: FAIL ({len(problems)} mismatches)')
    else:
        print('RESULT: PASS')
    if args.json:
        payload = {**observed, 'RESULT': 'FAIL' if problems else 'PASS'}
        payload['REFS'] = {'count': len(observed['REFS']), 'keys': observed['REFS']}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
