"""Template-specific planner inputs; structured templates need no slot layout."""
import json
from .template_engine import report_template


def planning_template(store, state, package):
    ref, definition = report_template(store, state.template_ref, package, allow_legacy_builtin=True)
    if definition is not None:
        return {
            'template_id': definition.get('id') or ref,
            'slot_goals': [
                {key: field[key] for key in ('id', 'semantic', 'owner', 'value_schema')}
                | {'binding': field.get('binding')}
                for field in definition['fields']
            ],
            'confirmed_scope_requirements': definition.get('scope_requirements',
                definition.get('rules', {}).get('scope_requirements', {})),
        }
    from core.layout import manifest_path
    manifest = json.loads(manifest_path(package).read_text(encoding='utf-8'))
    return {
        'template_id': manifest['template_id'],
        'slot_goals': [
            {key: field[key] for key in ('id', 'semantic', 'scope', 'statistical_unit', 'calculation', 'review_required')}
            | {'source_fields': field['source_fields_or_calculation']}
            for field in manifest['placeholders']
        ],
        'confirmed_scope_requirements': manifest['scope_requirements'],
    }
