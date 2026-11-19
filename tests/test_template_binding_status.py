"""The preview reflects effective package bindings without changing stored drafts."""
import copy

def binding_status(*args):
    from app.api_views.template_binding_status import binding_status as resolve
    return resolve(*args)


def test_unbound_then_package_bound_then_removed(monkeypatch):
    fields=[{'id':'manual','owner':'data','needs_binding':True,'binding':None},
            {'id':'writer','owner':'writer','needs_binding':True}]
    before=copy.deepcopy(fields)
    bindings={}
    monkeypatch.setattr('core.field_calculations.load',lambda package: bindings if package=='test_package' else {})
    assert binding_status(fields,'test_package')=={'pending':['manual'],'matched':[]}
    bindings['manual']={'metric':'report_year'}
    assert binding_status(fields,'test_package')=={'pending':[],'matched':['manual']}
    assert binding_status(fields,'another_package')=={'pending':['manual'],'matched':[]}
    bindings['manual']={'metric':'no_such_metric'}
    assert binding_status(fields,'test_package')=={'pending':['manual'],'matched':[]}
    assert fields==before


def test_inline_binding_precedence_and_invalid_spec(monkeypatch):
    monkeypatch.setattr('core.field_calculations.load',lambda _: {'bad':{'metric':'report_year'}})
    fields=[{'id':'inline','owner':'data','needs_binding':True,'binding':{'metric':'report_month'}},
            {'id':'bad','owner':'data','needs_binding':True,'binding':{'metric':'unknown_metric'}},
            {'id':'untracked','owner':'data','binding':{'metric':'report_year'}}]
    assert binding_status(fields,'test_package')=={'pending':['bad'],'matched':['inline']}


def test_draft_api_recomputes_status_without_rewriting_draft(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main
    from test_template_custom_field import _fixture, _custom
    store, task_id, _, _ = _fixture(tmp_path,monkeypatch)
    bindings={}
    monkeypatch.setattr('core.field_calculations.load',lambda _: bindings)
    with TestClient(main.app) as client:
        created=_custom(client,task_id,store.get_task(task_id).revision,text='重点关注',
            custom={'display_name':'本期数据','semantic':'本期统计','owner':'data'}).json()
        field_id=created['field']['id']
        before=client.get(f'/api/templates/{task_id}/draft').json()
        assert before['binding_status']=={'pending':[field_id],'matched':[]}
        ref=before['draft_ref'];revision=before['revision']
        bindings[field_id]={'metric':'report_year'}
        after=client.get(f'/api/templates/{task_id}/draft').json()
        assert after['binding_status']=={'pending':[],'matched':[field_id]}
        assert after['draft_ref']==ref and after['revision']==revision
        assert after['draft']['pending']['needs_binding']==[field_id]
        assert after['definition']==before['definition']
