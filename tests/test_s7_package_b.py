"""WP-S7-C：最小假客户包 B 的可加载/可跑/白名单/基座零改动（5 个用例）。

判据链（`docs/team/任务分解-S7.md` §1.2 G-PKG-B + §4.2 Z1/Z1'/Z4/Z5）：
    1 冒烟：`REPORT_PACKAGE=demo_b` 子进程跑到 `phase='awaiting_review'`，§1.2 的 13 行全部成立；
    2 身份：包名 / 图表数 / 提示词键集都是 B 的，不是 A 的；
    3 数据：`LOCALITY_HITS 景区片区=2`（A 的八区县在同一份样本上命中 0）——「不同」才是判据；
    4 白名单：**同一份样本、同一个 build_table 调用**，A 包下放行、B 包下 `tool_not_allowed`
      （负向对照；一个"永远拒绝"的门禁和一个"正确拒绝"的门禁是两件事）；
    5 基座：`CORE-HASH` 与 `APP-HASH` 与当前层基线逐字符相等（P7 最硬的一条；S8 起每层一档，
      现指 `core-S8-L5.json`）。

两个必须遵守的隔离约束：
    * B 的加载验证**只能在子进程**：四个注册表都是 module-global（`core/tools/vocabulary.py:16`
      等），进程内 `configure(demo_b)` 会污染后续 300+ 用例（§5 RISK-1）。
    * A 的负向对照**只能在本进程**（pytest 进程缺省就是 A），且先断言 `PACKAGE=='anshun_monthly'`
      ——否则「永远拒绝」与「正确拒绝」在观测上无法区分。
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import gate_core_iso  # noqa: E402

import app.config  # noqa: E402
from app.schemas import TaskState, ToolCall  # noqa: E402
from app.storage import Store  # noqa: E402
from app.tool_executor import RunContext, execute_tool  # noqa: E402

BASELINE = REPO / "docs" / "team" / "baseline" / "core-S8-L5.json"
SMOKE = REPO / "scripts" / "smoke_package_b.py"

PROMPT_KEYS = {
    'historical_researcher.plan', 'historical_researcher.research',
    'writer.analysis', 'writer.outlook', 'template_analyst.template',
    'event_judge.pairs', 'event_judge.top10', 'event_judge.repair',
    'event_classifier.classify', 'event_summarizer.summary',
}
A_LOCALITIES = {'西秀区', '平坝区', '普定县', '镇宁自治县', '关岭自治县',
                '紫云自治县', '黄果树旅游区', '安顺经开区'}
SMOKE_KEYS = {'PACKAGE', 'CHARTS', 'PROMPTS', 'ROLES', 'LOCALITIES', 'STYLE_SKILL',
              'CHART_CALLS', 'PHASE', 'REFS', 'FILTER_COUNTS', 'LOCALITY_HITS', 'REJECT', 'RESULT'}

_SMOKE_CACHE: dict = {}


def smoke() -> dict:
    """跑一次冒烟并缓存（每次运行会 spawn ~14 个子进程，两个用例共用一次）。"""
    if not _SMOKE_CACHE:
        env = {**os.environ, 'REPORT_PACKAGE': 'demo_b', 'PYTHONIOENCODING': 'utf-8'}
        done = subprocess.run([sys.executable, str(SMOKE), '--json'], cwd=str(REPO), env=env,
                              capture_output=True, text=True, encoding='utf-8', timeout=900)
        lines = [line for line in done.stdout.splitlines() if line.strip()]
        assert done.returncode == 0, f'smoke exit={done.returncode}\n{done.stdout}\n{done.stderr}'
        _SMOKE_CACHE.update(payload=json.loads(lines[-1]), stdout=done.stdout)
    return _SMOKE_CACHE['payload']


def test_smoke_runs_and_reports_b() -> None:
    payload = smoke()
    assert set(payload) == SMOKE_KEYS
    assert payload['RESULT'] == 'PASS'
    assert payload['PHASE'] == 'awaiting_review'
    assert payload['CHART_CALLS'] == 0
    assert payload['FILTER_COUNTS'] == {'positive': 2, 'neutral': 1, 'negative': 3,
                                        'warning': 2, 'union': 3}
    # 13 个保底步骤 + `filter_records` 别名 + 两条分析链 = 16（任务分解 §1.2 写 15，漏了别名，
    # 见 scripts/smoke_package_b.py:ALIAS_REFS 的说明）。
    assert payload['REFS']['count'] == 16
    assert {'event_analysis', 'event_analysis_checkpoint'} <= set(payload['REFS']['keys'])
    assert payload['REJECT'] == 'tool_not_allowed:build_table'


def test_package_identity_is_b() -> None:
    payload = smoke()
    assert payload['PACKAGE'] == 'demo_b'
    assert payload['CHARTS'] == ['sentiment', 'daily', 'platform']   # A 是 5 个
    assert set(payload['PROMPTS']) == PROMPT_KEYS                     # A 是 32 个
    assert payload['ROLES'] == ['event_judge', 'event_classifier', 'event_summarizer']
    assert payload['STYLE_SKILL'] == 'lieflat-less-ai-tone'


def test_vocabulary_is_b_not_a() -> None:
    payload = smoke()
    localities = set(payload['LOCALITIES'])
    assert {'景区片区', '中心城区'} <= localities
    assert localities & A_LOCALITIES == set()
    # 行为判据：B 的词典真的被读了；A 的八区县在这份样本上一条都命中不了。
    assert payload['LOCALITY_HITS'] == {'景区片区': 2}


def test_whitelist_is_per_package(tmp_path: pathlib.Path) -> None:
    """A 放行、B 拒绝——同一个工具、同一份参数，只有包不同。"""
    assert app.config.PACKAGE == 'anshun_monthly', (
        '本进程必须是 A 包：REPORT_PACKAGE 被设成别的值会让下面的"放行"对照失效（RISK-1）')

    store = Store(tmp_path / 'store')
    store.put_task(TaskState(id='a-side', kind='report', phase='processing', metadata={'mode': 'fallback'}))
    allowed = asyncio.run(execute_tool(
        ToolCall(call_id='a-side', tool_name='build_table', arguments={}, reason='负向对照'),
        RunContext(store, 'a-side')))
    # A 的 manifest.tools.allow 含 build_table → 策略放行；工具自身因为没有确认事件返回 needs_review。
    assert allowed.error_code is None
    assert allowed.status != 'error'

    assert smoke()['REJECT'] == 'tool_not_allowed:build_table'


def test_core_and_app_untouched() -> None:
    baseline = json.loads(BASELINE.read_text(encoding='utf-8-sig'))
    core_map = gate_core_iso.tree_hash(REPO / 'core', '*')
    assert gate_core_iso.tree_digest(REPO / 'core', '*') == baseline['core_hash']
    assert len(core_map) == baseline['core_files']
    assert gate_core_iso.tree_digest(REPO / 'app', '*.py') == baseline['app_hash']
