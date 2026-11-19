import pytest
from test_extended_calculations import report
from core.frozen_report import Calculation,MissingReportInput

def test_local_positive_activity_selection_excludes_negative_and_foreign():
    r=report()
    r.records=[
        {'id':'a','title':'龙川县委召开会议','summary':'部署本地工作','author':'龙川发布','source':'县政府','sentiment':'正面','media_attribute':'政务'},
        {'id':'b','title':'龙川县委召开会议','summary':'报道','author':'媒体','sentiment':'正面'},
        {'id':'c','title':'龙川食物中毒','summary':'县政府通报','author':'疾控','sentiment':'负面','media_attribute':'政务'},
        {'id':'d','title':'山西召开会议','summary':'外地活动','author':'山西政府','sentiment':'正面','media_attribute':'政务'},
    ]
    spec={'metric':'selected_material_count','sentiment':'正面','filters':{'media_attribute':['政务']},
          'selection_terms':[['龙川'],['县委','县政府']]}
    result=r.calculate(spec)
    assert result['selection']['title']=='龙川县委召开会议'
    assert result['value']=='2'
    r.records=r.records[2:]
    with pytest.raises(MissingReportInput):r.calculate(spec)

def test_media_organization_count_merges_accounts_and_requires_identity():
    r=report()
    r.records=[{'id':'1','author':'新闻网','source':'微信','source_id':'001'},
               {'id':'2','author':'新闻网客户端','source':'头条','source_id':'002'},
               {'id':'3','author':'日报','source':'网站','source_id':'003'}]
    spec={'metric':'distinct_organization_count','organization_aliases':{'新闻网客户端':'新闻网'}}
    assert r.calculate(spec)['value']=='2'
    r.records.append({'id':'4','author':'','source':'微信公众号','source_id':'004'})
    with pytest.raises(MissingReportInput,match='媒体机构身份'):r.calculate(spec)

def test_new_parameters_cannot_be_silently_ignored():
    with pytest.raises(ValueError):Calculation.model_validate({'metric':'count','selection_terms':[['龙川']]})
    with pytest.raises(ValueError):Calculation.model_validate({'metric':'count','organization_aliases':{'甲':'乙'}})

def test_candidate_grouping_merges_headlines_and_keeps_propagation_records(monkeypatch):
    r=report()
    r.records=[{'id':'1','title':'会议甲','summary':'活动','sentiment':'正面'},
               {'id':'2','title':'会议另一标题','summary':'活动','sentiment':'正面'},
               {'id':'3','title':'会议甲','summary':'转载','sentiment':'正面'}]
    monkeypatch.setattr('core.tools.dedup.group_by_representative',lambda rows,threshold:{'groups':[{'member_ids':['1','2','3']}],'method':{'type':'synthetic grouping'}})
    result=r.calculate({'metric':'selected_material_count','deduplicate_selection':True})
    assert result['value']=='3'
    assert len(result['selection']['candidates'])==1
    assert result['selection']['record_refs']==['1','2','3']

def test_propagation_does_not_include_foreign_event_with_same_title():
    r=report()
    r.records=[{'id':'1','title':'县委常委会召开会议','summary':'龙川县召开本地会议','sentiment':'正面'},
               {'id':'2','title':'县委常委会召开会议','summary':'保亭县召开会议','sentiment':'正面'}]
    result=r.calculate({'metric':'selected_material_count','selection_terms':[['龙川县']],'sentiment':'正面'})
    assert result['value']=='1'
    assert result['selection']['record_refs']==['1']

def test_institution_suffixes_and_author_fallback_preserve_article_count():
    r=report()
    r.records=[{'id':'1','author':'羊城派','source':'微信'},
               {'id':'2','author':'羊城派-河源','source':'头条'},
               {'id':'3','author':'','source':'羊城派-综合'},
               {'id':'4','author':'独立媒体','source':'羊城派'},
               {'id':'5','author':'羊城派-独立媒体','source':'网站'}]
    spec={'organization_aliases':{'羊城派':'羊城派'},'organization_suffixes':['河源','综合']}
    assert r.calculate({'metric':'distinct_organization_count',**spec})['value']=='3'
    names=r.calculate({'metric':'organization_names',**spec})['value']
    assert names.split('、')[0]=='羊城派'
    assert '羊城派-独立媒体' in names
    assert r.calculate({'metric':'filtered_record_count'})['value']=='5'
    assert r.records[2]['author']==''

def test_suffix_parameters_do_not_apply_to_unrelated_calculations():
    with pytest.raises(ValueError):Calculation.model_validate({'metric':'count','organization_suffixes':['综合']})
