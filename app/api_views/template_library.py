"""模板库列表与模板任务软删除（框架无关：不 import fastapi/HTTPException）。

软删除语义（用户需求：模板任务越积越多、同名无法重建）：
- 只在 ``TaskState.metadata`` 打 ``template_deleted_at`` 时间戳并把 phase 置 ``cancelled``，
  artifact 文件**一个都不删**（历史报告任务可能按 ``template_ref`` 回看工件）；
- 已删任务不再进 ``GET /api/templates``（模板库 02 页与 03 页下拉都从这个口取数）；
- 已被报告任务引用的已确认模板：默认拒绝并返回引用数，``force=True`` 才软删；
  报告任务自身的 ``template_ref`` 原封不动，仍可按工件查看；
- 删除是任务级标记，不占用模板名：新建同名模板任务走全新 task_id/artifact，
  旧任务已不再出现于列表，因此同名可以重新创建并确认。
"""
from __future__ import annotations

from datetime import datetime, timezone

#: 内置基线条目：逐字沿用原 main.templates() 的字面量（响应体形状不变）。
BASELINE_TEMPLATE = {
    'id': 'anshun-monthly-colored',
    'name': '安顺月报 · 五色逐项占位模板',
    'version': 1,
    'status': 'candidate_requires_review',
    'usable_for_final': False,
    'reason': '8 月标色 Word 已取得，颜色疑点与占位符口径待人工确认',
    'manifest_url': '/api/template-manifest',
}


#: 研判仍在后台跑的相位：此时软删会被跑完的模板图把 phase 写回，
#: 显式拒绝（UI 只对已出候选 / 已确认的任务给入口，正常流程碰不到）。
ACTIVE_TEMPLATE_PHASES = frozenset((
    'queued', 'template_parsing', 'template_local_ready', 'template_model_reviewing',
))


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_templates(store) -> list[dict]:
    """模板库条目：内置基线 + 未软删模板任务的已确认版本 / 待确认候选。

    与旧实现的唯一行为差异：待确认的候选任务也出现在库里（带 ``task_id``），
    前端因此能对「已确认」和「待确认」两类任务都提供删除入口；下拉仍只取
    ``confirmed_by_human``，候选条目不会混进新建报告的模板选择。
    """
    items = [dict(BASELINE_TEMPLATE)]
    for task in store.list_tasks():
        if task.kind != 'template' or task.metadata.get('template_deleted_at'):
            continue
        name = str(task.metadata.get('template_name') or '').strip()
        ref = task.metadata.get('confirmed_template_ref')
        if ref:
            try:
                artifact = store.get_artifact(ref)
            except (KeyError, FileNotFoundError, ValueError, OSError):
                continue
            if not artifact.get('writer_schema'):
                continue
            count = len(artifact.get('source_reports', []))
            items.append({
                'id': ref,
                'task_id': task.id,
                'name': name or str(artifact.get('name') or '').strip()
                        or f'{count} 份报告生成的结构化模板',
                'version': 1,
                'status': 'confirmed_by_human',
                'usable_for_final': False,
                'reason': '结构与 Schema 已确认；尚缺数据绑定的字段保留待填',
            })
        elif task.metadata.get('structured_template_ref') and not task.metadata.get('simulation'):
            items.append({
                'id': task.id,
                'task_id': task.id,
                'name': name or '待确认模板',
                'version': 1,
                'status': 'candidate_requires_review',
                'usable_for_final': False,
                'reason': '模型语义研判已完成，等待人工确认；确认后才能用于成稿',
            })
    return items


def report_reference_count(store, template_ref: str | None) -> int:
    """按已确认模板工件建过报告的报告任务数（报告任务不看软删，引用是历史事实）。"""
    if not template_ref:
        return 0
    return sum(1 for task in store.list_tasks()
               if task.kind == 'report' and task.template_ref == template_ref)


def soft_delete_template(store, task_id: str, force: bool = False):
    """软删除一个模板任务。返回 ``(error, payload)``：error=(status, code) 由路由转 HTTP。"""
    try:
        state = store.get_task(task_id)
    except KeyError:
        return (404, 'task_not_found'), None
    if state.kind != 'template':
        return (422, 'not_template_task'), None
    if state.metadata.get('template_deleted_at'):
        return (409, 'template_already_deleted'), None
    if state.phase in ACTIVE_TEMPLATE_PHASES and not state.cancel_requested:
        return (409, 'template_still_running'), None
    ref = state.metadata.get('confirmed_template_ref')
    references = report_reference_count(store, ref)
    if references and not force:
        return (409, 'template_in_use'), {'references': references, 'task_id': task_id}
    state.metadata['template_deleted_at'] = _stamp()
    # 记住删除前相位，仅作审计；恢复需求出现前不提供 undelete。
    state.metadata['template_phase_before_delete'] = state.phase
    state.phase = 'cancelled'
    # 协作取消标志：若研判后台图仍在跑，让它在既有检查点停下（不删任何产物）。
    state.cancel_requested = True
    store.put_task(state, state.revision)
    store.append_event(task_id, {
        'type': 'template_task_deleted', 'soft': True,
        'confirmed': bool(ref), 'references': references,
        'forced': bool(references and force),
    })
    return None, {
        'task_id': task_id, 'phase': 'cancelled', 'references': references,
        'deleted_at': state.metadata['template_deleted_at'],
    }
