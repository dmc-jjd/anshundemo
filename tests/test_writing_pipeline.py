"""Pure repair state keeps valid prose and positions through failed later rounds."""
from types import SimpleNamespace


def test_repair_state_locks_valid_items_and_preserves_latest_invalid():
    from app.writing_pipeline.outlook_repair import OutlookRepairState
    from app.section_two import OutlookItemValidationError
    from test_section_two import seasonal_outlook_item
    from core.section_schema import OutlookItem
    topics = [{'category': key, 'knowledge_ref': key, 'basis_type': 'seasonal', 'evidence': []}
              for key in ('交通管理', '安全生产')]
    history = {'topics': topics, 'window': {}}
    repair = OutlookRepairState(history)
    items = [OutlookItem.model_validate(seasonal_outlook_item(topic)) for topic in topics]
    def render(item, *args, **kwargs):
        if item.category == '安全生产':
            raise OutlookItemValidationError('wrong source', item.category, ['安全生产'], 'category_source_mismatch')
        return item.paragraph, item.history_refs
    valid = repair.accept(items, False, render, 'anshun_monthly', {})
    assert [entry['category'] for entry in valid] == ['交通管理']
    original = items[0].paragraph
    items[0].paragraph = 'should be ignored'
    items[1].paragraph += '保留最新待核查正文。'
    repair.accept(items, True, render, 'anshun_monthly', {})
    assert repair.locked['交通管理']['text'] == original
    assert repair.invalid[0]['item']['paragraph'] == items[1].paragraph
    feedback, errors = repair.feedback(SimpleNamespace(reverse={'安全生产': 14}), 4)
    assert feedback['invalid_items'][0]['allowed_numbers'] == [14] and errors
    pending = repair.pending('field', 'fact', 'template')
    assert pending['value'] == [original, items[1].paragraph]
    assert pending['status'] == 'writer_source_pending'
