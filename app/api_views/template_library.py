"""模板库列表与模板任务硬删除（框架无关：不 import fastapi/HTTPException）。

硬删除语义（用户需求：二次建包 / 更新提示词时，agent 读盘扫描不能再看到已删模板）：
- 从任务表永久删除该模板任务，并删除其事件、审核草稿，以及未被报告引用的工件文件；
- ``GET /api/templates`` 与新建报告的模板下拉不再列出该任务（任务已不存在）；
- ``store.list_tasks()`` 同样看不到该任务，建包 skill 的读盘扫描不会再命中已删模板；
- 已被报告任务引用的已确认模板：默认拒绝并返回引用数，``force=True`` 才删除任务；
  此时只保留已确认 ``template_version`` 工件，报告任务的 ``template_ref`` 原封不动，仍可回看；
- 删除不占用模板名：新建同名模板任务走全新 task_id/artifact，因此同名可以重新创建并确认。
"""
from __future__ import annotations


#: 研判仍在后台跑的相位：此时硬删会让后台图写到已不存在的任务，
#: 显式拒绝（UI 只对已出候选 / 已确认的任务给入口，正常流程碰不到）。
ACTIVE_TEMPLATE_PHASES = frozenset((
    'queued', 'template_parsing', 'template_local_ready', 'template_model_reviewing',
))


def list_templates(store, package=None) -> list[dict]:
    """模板库条目：当前包声明的内置模板 + 仍存在的模板任务的已确认版本 / 待确认候选。

    与旧实现的唯一行为差异：待确认的候选任务也出现在库里（带 ``task_id``），
    前端因此能对「已确认」和「待确认」两类任务都提供删除入口；下拉仍只取
    ``confirmed_by_human``，候选条目不会混进新建报告的模板选择。

    历史上软删除留下的 ``template_deleted_at`` 任务仍会被跳过；调用
    ``purge_soft_deleted_templates`` 后这类残留会被硬删除。
    """
    from ..template_engine import builtin_templates
    items = [dict(item) for item in builtin_templates(package)]
    for task in store.list_tasks():
        if task.kind != 'template' or task.metadata.get('template_deleted_at'):
            continue
        name = str(task.metadata.get('template_name') or '').strip()
        ref = task.metadata.get('confirmed_template_ref')
        if ref:
            try:
                artifact = store.get_artifact(ref)
            except (KeyError, FileNotFoundError, ValueError, OSError):
                items.append({
                    'id': ref,
                    'task_id': task.id,
                    'name': name or '已确认模板',
                    'version': 1,
                    'status': 'confirmed_by_human',
                    'usable_for_final': False,
                    'reason': '已确认模板文件读取失败，请检查工件完整性',
                })
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
    """按已确认模板工件建过报告的报告任务数（报告任务不看删除标记，引用是历史事实）。"""
    if not template_ref:
        return 0
    return sum(1 for task in store.list_tasks()
               if task.kind == 'report' and task.template_ref == template_ref)


def delete_template(store, task_id: str, force: bool = False):
    """硬删除一个模板任务。返回 ``(error, payload)``：error=(status, code) 由路由转 HTTP。

    任务从表中移除；未被报告引用的工件从库和磁盘删除。若 ``force`` 且仍有报告引用
    已确认模板，则只保留该 ``template_version``，以便历史报告按 ``template_ref`` 回看。
    历史上已软删除的残留任务再次删除时，直接完成硬删除，不再返回
    ``template_already_deleted``。
    """
    try:
        state = store.get_task(task_id)
    except KeyError:
        return (404, 'task_not_found'), None
    if state.kind != 'template':
        return (422, 'not_template_task'), None
    if state.phase in ACTIVE_TEMPLATE_PHASES and not state.cancel_requested:
        return (409, 'template_still_running'), None
    ref = state.metadata.get('confirmed_template_ref')
    references = report_reference_count(store, ref)
    if references and not force:
        return (409, 'template_in_use'), {'references': references, 'task_id': task_id}
    keep = [ref] if references and ref else []
    removed = store.delete_task(task_id, keep_artifact_ids=keep)
    return None, {
        'ok': True,
        'task_id': task_id,
        'deleted': True,
        'hard': True,
        'references': references,
        'kept_artifacts': keep,
        'removed_artifacts': removed,
    }


# 旧名保留，避免尚未更新的调用方立刻断掉。
soft_delete_template = delete_template


def purge_soft_deleted_templates(store) -> list[dict]:
    """把历史上软删除留下的模板任务改为硬删除。

    仍被报告引用的已确认 ``template_version`` 会保留，其它工件一并删除。
    """
    leftovers = [
        task for task in store.list_tasks()
        if task.kind == 'template' and task.metadata.get('template_deleted_at')
    ]
    results = []
    for task in leftovers:
        error, payload = delete_template(store, task.id, force=True)
        results.append({'task_id': task.id, 'error': error, 'payload': payload})
    return results
