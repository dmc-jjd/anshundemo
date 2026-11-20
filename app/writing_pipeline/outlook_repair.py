"""Bounded outlook repair state; rendering is injected by the public writer."""
from ..section_two import OutlookItemValidationError


class OutlookRepairState:
    def __init__(self, history):
        self.history = history
        self.locked = {}
        self.invalid = []
        self.positions = {}

    def allowed_refs(self, category):
        topic = next((t for t in self.history['topics'] if t['category'] == category), None) if self.history else None
        return sorted(({c['page_ref'] for c in topic['evidence']} |
                       ({topic['knowledge_ref']} if topic.get('knowledge_ref') else set())) if topic else set())

    def _invalid(self, item, index, code, message, allowed_refs=None):
        return {'item_index': index, 'category': item.category, 'error_code': code, 'message': message,
                'item': item.model_dump(), 'allowed_refs': self.allowed_refs(item.category) if allowed_refs is None else sorted(allowed_refs)}

    def accept(self, items, repairing, render, package, policy):
        if not repairing:
            self.positions = {item.category: index for index, item in enumerate(items)}
        retry_categories = {entry['category'] for entry in self.invalid}
        topic_categories = {t['category'] for t in self.history['topics']}
        counts = {category: sum(i.category == category for i in items) for category in {i.category for i in items}}
        duplicates = {category for category, count in counts.items() if count > 1}
        accepted = {item.category for item in items if item.category not in self.locked and
                    (not repairing or item.category in retry_categories or item.category in topic_categories)}
        self.invalid[:] = [entry for entry in self.invalid if entry['category'] not in accepted]
        for index, item in enumerate(items):
            if item.category in self.locked or (repairing and item.category not in retry_categories and item.category not in topic_categories):
                continue
            raw_item = item.model_copy(deep=True)
            if item.category in duplicates:
                invalid = self._invalid(raw_item, index, 'duplicate_category', '前瞻类别重复：'+item.category+'；每个类别只能保留一条。')
            elif not item.paragraph:
                invalid = self._invalid(raw_item, index, 'missing_paragraph', '每类风险必须提供自然完整的paragraph正文；不能省略正文后靠拼接审计字段成稿。')
            else:
                topic = next((t for t in self.history['topics'] if t['category'] == item.category), None)
                if topic:
                    item.basis_type = topic.get('basis_type', 'historical')
                try:
                    text, refs = render(item, self.history['topics'], self.history['window'], package=package, policy=policy)
                    self.locked[item.category] = {'item_index': index, 'position': self.positions.get(item.category, index),
                                                  'category': item.category, 'item': item.model_dump(), 'text': text, 'refs': refs}
                    self.invalid[:] = [entry for entry in self.invalid if entry['category'] != item.category]
                    continue
                except OutlookItemValidationError as exc:
                    invalid = self._invalid(raw_item, index, exc.code, str(exc), exc.allowed_refs)
            self.invalid.append(invalid)
        return sorted(self.locked.values(), key=lambda entry: entry['position'])

    def feedback(self, catalog, minimum):
        items = []
        for entry in self.invalid:
            numbers = [catalog.reverse[ref] for ref in entry['allowed_refs'] if ref in catalog.reverse]
            message = '前瞻类别和历史来源未对应；只能使用本类别允许资料编号。' if entry['error_code'] == 'category_source_mismatch' else entry['message']
            items.append({**entry, 'message': message, 'allowed_numbers': numbers})
        errors = [entry['category']+'：'+entry['message']+'；允许资料编号：'+(','.join(map(str, entry['allowed_numbers'])) or '无') for entry in items]
        return {'invalid_items': items}, errors or [f'前瞻合格类别不足{minimum}类；请仅补充或替换尚未合格的类别。']

    def pending(self, field_id, fact_ref, template_ref):
        valid = sorted(self.locked.values(), key=lambda e: e['position'])
        invalid = list({e['category']: e for e in self.invalid}.values())
        if not valid and not invalid:
            return None
        source_only = bool(invalid) and all(e.get('error_code') == 'category_source_mismatch' for e in invalid)
        merged = [{'position': e['position'], 'valid': True, 'category': e['category'], 'text': e['text']} for e in valid]
        merged += [{'position': e.get('item_index', 0), 'valid': False, 'category': e['category'],
                    'text': e['item'].get('paragraph') or e['item'].get('historical_basis', '')} for e in invalid]
        merged.sort(key=lambda x: (x['position'], 0 if x['valid'] else 1))
        return {
            'field_id': field_id,
            'valid_items': [{k: e[k] for k in ('category', 'item', 'text', 'refs', 'position')} for e in valid],
            'invalid_items': [{'item_index': e.get('item_index'), 'category': e['category'], 'item': e['item'],
                               'error_code': e.get('error_code'), 'message': e.get('message'), 'allowed_refs': e.get('allowed_refs', [])} for e in invalid],
            'outlook_items': [{k: e[k] for k in ('category', 'text', 'valid')} for e in merged],
            'value': [e['text'] for e in merged],
            'reason': '正文已生成，引用或校验未能在限定轮次内完成；候选正文与逐项错误已保留，供最终人工核对。',
            'fact_ref': fact_ref, 'template_ref': template_ref,
            'status': 'writer_source_pending' if source_only else 'writer_validation_pending',
        }
def split_outlook_fields(ids,texts,refs,fields):
    """Keep optional trailing paragraphs empty instead of merging a list into field one."""
    if not ids or len(texts)>len(ids):return None
    if any(not fields[key].get('optional') for key in ids[len(texts):]):return None
    return {key:{'value':texts[index] if index<len(texts) else '', 'source_refs':list(refs)} for index,key in enumerate(ids)}
