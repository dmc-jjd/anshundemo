import json
from types import SimpleNamespace
from app.api_views import prompt_adaptation as subject


def setup_package(tmp_path,monkeypatch):
    prompts=tmp_path/'prompts';prompts.mkdir();(prompts/'index.yaml').write_text('index')
    bundle={'prompts':{'writer.general':'old text'},'roles':{'writer':{'output':'text'}},'report_profiles':{},'default_profile':'default','template_policy':{}}
    package=SimpleNamespace(directory=tmp_path,prompt_bundle=bundle)
    monkeypatch.setattr(subject,'load_package',lambda _:package)
    return bundle


def test_missing_history_does_not_invent_generation_time(tmp_path,monkeypatch):
    setup_package(tmp_path,monkeypatch)
    result=subject.prompt_status('test',[{'id':'template_version-a','name':'report','status':'confirmed_by_human'}])
    assert result['generated_at'] is None and result['files_updated_at']
    assert result['templates'][0]['status']=='unrecorded'


def test_adaptation_changes_when_effective_prompts_change(tmp_path,monkeypatch):
    bundle=setup_package(tmp_path,monkeypatch)
    digest=subject.bundle_digest(bundle)
    record={'schema_version':1,'generated_at':'2026-11-19T02:00:00+00:00','bundle_digest':digest,
        'templates':[{'template_ref':'template_version-a','adapted_at':'2026-11-19T02:00:00+00:00','bundle_digest':digest,'status':'adapted'}]}
    (tmp_path/'prompts'/'adaptation.json').write_text(json.dumps(record))
    templates=[{'id':'template_version-a','name':'old','status':'confirmed_by_human'}, {'id':'template_version-b','name':'new','status':'confirmed_by_human'}]
    result=subject.prompt_status('test',templates)
    assert [x['status'] for x in result['templates']]==['adapted','unrecorded']
    bundle['prompts']['writer.general']='changed text'
    result=subject.prompt_status('test',templates)
    assert result['templates'][0]['status']=='stale'
    assert result['generated_at'] is None


def test_pending_record_and_corrupt_metadata_are_visible(tmp_path,monkeypatch):
    setup_package(tmp_path,monkeypatch)
    record={'schema_version':1,'templates':[{'template_ref':'v-new','status':'pending','note':'提示词尚未更新'}]}
    path=tmp_path/'prompts'/'adaptation.json';path.write_text(json.dumps(record))
    templates=[{'id':'v-new','status':'confirmed_by_human'}]
    assert subject.prompt_status('test',templates)['templates'][0]['status']=='pending'
    path.write_text('{broken')
    result=subject.prompt_status('test',templates)
    assert result['record_error'] and result['templates'][0]['status']=='unrecorded'


def test_endpoint_uses_selected_package(monkeypatch,tmp_path):
    import app.main as main
    from fastapi.testclient import TestClient
    import app.api_views.template_library as library
    setup_package(tmp_path,monkeypatch)
    seen=[]
    monkeypatch.setattr('app.packages_api.resolve_package',lambda name: name)
    monkeypatch.setattr(library,'list_templates',lambda store,package: seen.append(package) or [])
    with TestClient(main.app) as client:
        response=client.get('/api/prompt-status',headers={'X-Report-Package':'other-package'})
    assert response.status_code==200 and response.json()['package']=='other-package'
    assert seen==['other-package']


def test_record_cli_writes_actual_digest_and_rejects_unknown_template(tmp_path,monkeypatch):
    import io
    import sys
    import pytest
    import core.packages
    from scripts import record_prompt_adaptation as command
    bundle=setup_package(tmp_path,monkeypatch)
    package=SimpleNamespace(directory=tmp_path,prompt_bundle=bundle)
    monkeypatch.setattr(core.packages,'load_package',lambda _: package)
    monkeypatch.setattr(command.urllib.request,'urlopen',lambda *a,**k: io.StringIO(json.dumps([
        {'id':'v-confirmed','status':'confirmed_by_human','artifact_status':'available'}])))
    argv=['record','--package','test','--template-id','v-confirmed','--generated-at','2026-11-18T00:00:00+00:00']
    monkeypatch.setattr(sys,'argv',argv)
    command.main()
    path=tmp_path/'prompts'/'adaptation.json'
    record=json.loads(path.read_text())
    assert record['bundle_digest']==subject.bundle_digest(bundle)
    assert record['templates'][0]['status']=='adapted' and record['templates'][0]['adapted_at']
    before=path.read_bytes()
    monkeypatch.setattr(sys,'argv',[x if x!='v-confirmed' else 'v-unknown' for x in argv])
    with pytest.raises(SystemExit):command.main()
    assert path.read_bytes()==before
