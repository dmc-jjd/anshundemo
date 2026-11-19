"""HTTP-free report creation: validate first, freeze package context, then persist."""
import uuid
from core.schemas import TaskState
from core.task_package import resolve_task_package
from core.tools import vocabulary
from app.fallback_policy import event_scope_metadata
from app.template_engine import report_template
from app.workflow import task_feature_snapshot


class ReportRequestError(ValueError):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail
        super().__init__(detail)


def prepare_report(store, request, paths, package):
    if len(paths) != 1 or not paths[0].lower().endswith('.xlsx'):
        raise ReportRequestError(422, 'one_xlsx_required')
    package = resolve_task_package(package, store=store)
    try:
        ref, definition = report_template(store, request.template_ref, package)
    except ValueError as exc:
        raise ReportRequestError(409, str(exc)) from exc
    rules = definition.get('rules', {}) if definition is not None else {}
    from core.writing_contracts import resolve
    try:contract=resolve(definition or {},package,ref)
    except (ValueError,TypeError) as exc:raise ReportRequestError(422,'writing_contract_invalid: '+str(exc)) from exc
    rules={**rules,'features':{**rules.get('features',{}),**contract.get('feature_overrides',{})}}
    sheet = request.sheet_index if request.sheet_index is not None else vocabulary.sheet_index(package)
    return TaskState(
        id=uuid.uuid4().hex, package=package, kind='report', phase='queued',
        template_ref=ref, input_refs=request.file_ids,
        metadata={
            'input_path': paths[0], 'report_month': request.report_month,
            'report_issue': request.issue_number, 'report_date': request.publication_date,
            'sheet_index': sheet, 'mode': request.mode, **event_scope_metadata(package),
            'template_rules': task_feature_snapshot(rules, package),
            'writing_contract':contract,
            'event_threshold': request.event_threshold or rules.get('event_threshold', .65),
        },
    )


def persist_report(store, state, request, idempotency_key=None):
    parameters = {key: value for key, value in request.model_dump(mode='json').items()
                  if key in ('issue_number', 'publication_date') and value is not None}
    return store.create_report_once(state, parameters, 'report:'+idempotency_key if idempotency_key else None)


def enqueue_report(store, state, background_tasks, runner, deps):
    from core.storage import ConflictError
    attempt=uuid.uuid4().hex
    state.metadata.update(report_dispatch='registered',report_dispatch_attempt=attempt)
    def failed_registration():
        current=store.get_task(state.id)
        if current.metadata.get('report_dispatch_attempt')==attempt:
            current.metadata['report_dispatch']='failed'
            store.put_task(current,current.revision)
    try:
        store.put_task(state,state.revision)
    except ConflictError:
        return store.get_task(state.id)
    except Exception:
        failed_registration()
        raise
    try:
        background_tasks.add_task(runner,deps,state.id)
    except Exception:
        failed_registration()
        raise
    return state
