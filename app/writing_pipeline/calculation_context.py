"""Package-declared links between deterministic material selections and writing."""
import re


def build_contexts(fields, report, values, plans, package):
    if not package:
        return []
    from core.packages import load_package
    from ..structured_writer import calculation_for
    config = load_package(package).template.get('calculation_contexts') or {}
    if not isinstance(config, dict):
        raise ValueError('calculation_contexts_must_be_mapping')
    contexts = []
    for data_field, targets in config.items():
        # A package may be shared by several immutable template versions.
        if data_field not in fields:
            continue
        if not isinstance(targets, dict) or set(targets) - {'title_field', 'list_field'}:
            raise ValueError('invalid_calculation_context:' + data_field)
        if any(key not in fields or fields[key]['owner'] != 'writer' for key in targets.values()):
            raise ValueError('calculation_context_target_missing:' + data_field)
        if data_field not in values:
            continue  # Calculation failure is already recorded in data_values issues.
        result = calculation_for(fields[data_field], report, plans, package=package)
        selection = result.get('selection')
        if not selection or str(selection['count']) != str(values[data_field]['value']):
            raise ValueError('calculation_selection_required:' + data_field)
        contexts.append({'data_field': data_field, **targets,
                         'selection': {k: selection[k] for k in ('title', 'count', 'candidates')},
                         'source_refs': result['source_refs']})
    return contexts


def validate_selection(field_id, answer, contexts):
    text = str(answer.get('value') or '').strip()
    for context in contexts:
        title = context['selection']['title']
        if context.get('title_field') == field_id and text != title:
            raise ValueError('该字段必须使用程序选题标题：' + title)
        if context.get('list_field') == field_id:
            titles = re.findall(r'《([^《》]+)》', text)
            candidates = {item['title'] for item in context['selection']['candidates']}
            if title not in titles or any(item not in candidates for item in titles):
                raise ValueError('标题列举必须来自程序选题候选，并包含传播量对应标题：' + title)
