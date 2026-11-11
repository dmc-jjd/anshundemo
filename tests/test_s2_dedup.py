import pytest

import app.event_grouping as shell
import core.tools.dedup as dedup


def record(id, title, summary=''):
    return {'id': id, 'title': title, 'summary': summary}


def test_shell_and_core_are_same_object():
    assert shell.group_by_representative is dedup.group_by_representative


def test_representative_prevents_transitive_merge():
    a = record('a', 'alpha bravo'); b = record('b', 'alpha bravo charlie'); c = record('c', 'bravo charlie')
    result = dedup.group_by_representative([a, b, c], .7)
    assert [g['member_ids'] for g in result['groups']] == [['a', 'b'], ['c']]
    assert dedup.group_by_representative([b, c], .7)['groups'][0]['member_ids'] == ['b', 'c']
    assert result['groups'][0]['representative_id'] == 'a'


def test_threshold_out_of_range_keeps_original_message():
    rows = [record('a', 'alpha bravo')]
    with pytest.raises(ValueError) as exc:
        dedup.group_by_representative(rows, 1.1)
    assert str(exc.value) == 'similarity_threshold_must_be_between_zero_and_one'
