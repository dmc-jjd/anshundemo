"""Framework-free task deletion with running-task and template reference protection."""
from .template_library import delete_template

# Only stable human checkpoints or terminal phases can be removed.
DELETABLE_PHASES = frozenset((
    'paused', 'cancelled', 'failed', 'approved', 'awaiting_review', 'analysis_pending',
    'facts_frozen', 'awaiting_final_review', 'awaiting_template_confirmation',
    'template_confirmed', 'template_manual_review', 'template_review_failed',
))


def delete_task(store, task_id, force=False):
    try:
        state = store.get_task(task_id)
    except KeyError:
        return (404, 'task_not_found'), None
    if state.kind == 'template':
        return delete_template(store, task_id, force)
    if state.phase not in DELETABLE_PHASES:
        return (409, 'task_still_running'), None
    removed = store.delete_task(task_id)
    return None, {'ok': True, 'task_id': task_id, 'hard': True, 'deleted': True,
                  'removed_artifacts': removed}
