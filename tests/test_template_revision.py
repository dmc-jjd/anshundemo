import copy
import hashlib
import pytest
from core.schemas import TaskState
from test_frozen_writer import fixture
from app.template_revision import derive,valid_revision_source

def test_revision_is_idempotent_unconfirmed_and_preserves_confirmed_source(tmp_path):
    store,template=fixture(tmp_path)
    path=template['layout_source'];sha=hashlib.sha256(open(path,'rb').read()).hexdigest()
    template['source_reports']=[{'path':path,'sha256':sha},{'path':path,'sha256':sha}]
    oldref=store.put_artifact('old','template_version',template)
    original=copy.deepcopy(template)
    source=TaskState(id='old',kind='template',phase='template_confirmed',metadata={'confirmed_template_ref':oldref,'template_input_ref':store.put_artifact('old','input',{}),'comparison_ref':'comparison'})
    store.put_task(source)
    source=store.get_task('old')
    candidate=derive(store,'old',source.revision,'修订候选','已授权结构修订','one')
    assert candidate.phase=='awaiting_template_confirmation'
    assert not candidate.metadata.get('confirmed_template_ref')
    assert derive(store,'old',source.revision,'修订候选','已授权结构修订','one').id==candidate.id
    value=store.get_artifact(candidate.metadata['structured_template_ref'])
    assert valid_revision_source(store,candidate,value)
    assert value['status']=='candidate'
    assert store.get_artifact(oldref)==original and store.get_task('old')==source
    value['revision_source']['template_hash']='fake'
    assert not valid_revision_source(store,candidate,value)
    with pytest.raises(ValueError,match='stale'):derive(store,'old',source.revision+1,'候选','修订','two')
