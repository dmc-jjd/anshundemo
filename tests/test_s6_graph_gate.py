"""WP-S6-A：G-GRAPH 尺子的守卫用例（不在测试里复制期望哈希——尺子只有一把）。

判据来源：`docs/team/baseline/graph-S6.json`（唯一由 `scripts/gate_graph.py --record` 生成）。
注意：该基线**与 `任务分解-S6.md` §1 的 6 行旧值不再对齐**（ORDER/FINISH 四行逐字命中，
其余为过期值，勘误写在 `scripts/gate_graph.py` 的模块 docstring 与本包交付报告里）。

这里有两个方向相反的守卫，缺一不可：
    * 确定性：同进程/跨进程同值（否则门禁永远红）。
    * 灵敏度：定向改动后目标分量必变，且只变它（否则门禁永远绿 = 一份废纸）。

用例与断言的映射（5 个用例，逐条覆盖规格 5 项 + 队长条件 2 的四分量灵敏度）：
    1 test_graph_matches_baseline .................. 与基线逐分量比对
    2 test_graph_deterministic_in_process ........... 同进程连跑两次同值
    3 test_role_sequence_is_asserted ................ 退化 adapter 必须在 ROLES 处失败
    4 test_components_are_sensitive_to_targeted_change
        ① ORDER ② FINISH ③ ARTIFACTS(工件字段) ④ CALLS ⑤ ARTIFACTS(输入字节，
        原规格 `test_input_freeze_is_required` 的断言逐字保留在此：不冻结 → 摘要必变，
        证明 freeze() 不是装饰)
    5 test_gate_has_no_import_side_effects .......... import 纯性（不打印/不写文件）
"""
import importlib
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))

import gate_graph  # noqa: E402  尺子只有一把


def test_graph_matches_baseline():
    baseline = gate_graph.load_baseline()
    actual = gate_graph.run_all()
    for name in gate_graph.SCENARIOS:
        for component in gate_graph.COMPONENTS + ('TOTAL',):
            assert actual[name][component] == baseline[name][component], (
                f'{name}-{component} 与基线不符（先确认是有意变更，再 --record --force）')


def test_graph_deterministic_in_process():
    first = gate_graph.run_all()
    second = gate_graph.run_all()
    for name in gate_graph.SCENARIOS:
        assert first[name]['TOTAL'] == second[name]['TOTAL'], f'{name} 同进程两次不同值'


def test_role_sequence_is_asserted():
    """退化 adapter（description='d' 违反 min_length=4）必须在 ROLES 断言处失败，而不是"摘要变了"。"""
    with pytest.raises(gate_graph.GateAssertion, match='ROLES'):
        gate_graph.run_scenario('R3', adapter=gate_graph.r3_adapter('d'))


def test_components_are_sensitive_to_targeted_change():
    """四个分量各自的灵敏度 + 隔离性（只动目标分量）。

    每次改动都模拟"图/输入真的变了"，若某分量对这类改动无反应，它就是在给退化运行发绿灯。
    """
    control = gate_graph.run_scenario('R2')

    def changed(mutated):
        return {name: mutated[name] != control[name] for name in gate_graph.COMPONENTS}

    # ① ORDER：图上多一个节点执行（多一条 started 事件）
    with pytest.MonkeyPatch.context() as mp:
        import app.workflow as workflow
        original = workflow._graph_node

        def extra_node(deps, name, action, graph_name):
            node = original(deps, name, action, graph_name)
            if name != 'local_validation':
                return node

            async def injected(value):
                deps.store.append_event(value['task_id'], {'type': 'graph_node', 'graph': graph_name,
                                                           'node': 'injected_node', 'status': 'started'})
                return await node(value)

            return injected

        mp.setattr(workflow, '_graph_node', extra_node)
        diff = changed(gate_graph.run_scenario('R2'))
    assert diff == {'ORDER': True, 'FINISH': False, 'ARTIFACTS': False, 'CALLS': False}, diff

    # ② FINISH：某节点落地后的相位变了（多一条 finished，phase 不同）
    with pytest.MonkeyPatch.context() as mp:
        import app.workflow as workflow
        original = workflow._graph_node

        def extra_finish(deps, name, action, graph_name):
            node = original(deps, name, action, graph_name)
            if name != 'local_validation':
                return node

            async def injected(value):
                result = await node(value)
                deps.store.append_event(value['task_id'], {'type': 'graph_node', 'graph': graph_name,
                                                           'node': name, 'status': 'finished',
                                                           'phase': 'mutated_phase'})
                return result

            return injected

        mp.setattr(workflow, '_graph_node', extra_finish)
        diff = changed(gate_graph.run_scenario('R2'))
    assert diff == {'ORDER': False, 'FINISH': True, 'ARTIFACTS': False, 'CALLS': False}, diff

    # ③ ARTIFACTS：工件里的字段值变了（模型输出换一句话，入参不变）
    from test_writing_graph import clean_review

    async def mutated_reply(role, payload):
        reply = clean_review(payload)
        reply['summary'] = reply['summary'] + '（灵敏度探针）'
        return reply

    diff = changed(gate_graph.run_scenario('R2', adapter=mutated_reply))
    assert diff == {'ORDER': False, 'FINISH': False, 'ARTIFACTS': True, 'CALLS': False}, diff

    # ④ CALLS：发给模型的入参变了（图、工件都不动）
    with pytest.MonkeyPatch.context() as mp:
        import app.reviewers as reviewers
        original_payload_for = reviewers.payload_for

        def extra_payload(store, state, role):
            draft, fields, machine, payload, style = original_payload_for(store, state, role)
            payload['sensitivity_probe'] = '模型入参被改动'
            return draft, fields, machine, payload, style

        mp.setattr(reviewers, 'payload_for', extra_payload)
        diff = changed(gate_graph.run_scenario('R2'))
    assert diff == {'ORDER': False, 'FINISH': False, 'ARTIFACTS': False, 'CALLS': True}, diff

    # ⑤ ARTIFACTS 的输入层：输入字节不冻结（跨 tick）→ R1 摘要必变。
    #    即原规格 `test_input_freeze_is_required` 的断言：证明 freeze() 不是装饰。
    from test_api_flow import sample_xlsx

    raw = sample_xlsx()
    first = gate_graph.run_scenario('R1', xlsx=gate_graph._rezip(raw, (2026, 1, 1, 0, 0, 0)))
    second = gate_graph.run_scenario('R1', xlsx=gate_graph._rezip(raw, (2026, 1, 1, 0, 0, 2)))
    assert first['ARTIFACTS'] != second['ARTIFACTS'], '输入未冻结但 ARTIFACTS 不变：freeze() 已失效'


def test_gate_has_no_import_side_effects(capsys):
    importlib.reload(gate_graph)
    assert capsys.readouterr().out == ''
