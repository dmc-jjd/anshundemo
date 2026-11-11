import pytest
from app.event_grouping import group_by_representative

def record(id,title,summary=''):
    return {'id':id,'title':title,'summary':summary}

def test_representative_prevents_transitive_merge():
    a=record('a','alpha bravo');b=record('b','alpha bravo charlie');c=record('c','bravo charlie')
    result=group_by_representative([a,b,c],.7)
    assert [g['member_ids'] for g in result['groups']]==[['a','b'],['c']]
    assert group_by_representative([b,c],.7)['groups'][0]['member_ids']==['b','c']
    assert result['groups'][0]['representative_id']=='a'

def test_summary_changes_grouping_and_source_members_are_complete():
    rows=[record('1','本地消息','某桥交通事故后续恢复通行'),record('2','本地消息','学校举办秋季文艺汇演'),record('3','本地消息','某桥交通事故后续恢复通行')]
    result=group_by_representative(rows,.8)
    assert len(result['groups'])==2
    assert result['groups'][0]['member_ids']==['1','3']
    assert sorted(r for g in result['groups'] for r in g['member_ids'])==['1','2','3']
    with pytest.raises(ValueError):group_by_representative(rows,1.1)

def test_empty_titles_are_not_merged_without_evidence():
    result=group_by_representative([record('a',''),record('b','')],.5)
    assert len(result['groups'])==2
