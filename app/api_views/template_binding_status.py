"""Read-only status for manually introduced data fields and package bindings."""
from core.frozen_report import Calculation


def binding_status(fields, package=None):
    # Match the writer precedence, without relying on a future model plan.
    from app.writing_pipeline.calculations import KNOWN
    from app.template_review import binding_allowed
    import core.field_calculations
    configured = core.field_calculations.load(package)
    result = {'pending': [], 'matched': []}
    for field in fields:
        if field.get('owner') != 'data' or not field.get('needs_binding'):
            continue
        binding = field.get('binding') or {}
        spec = KNOWN.get(field['id']) or (binding if binding.get('metric') else configured.get(field['id']))
        if spec:
            try:
                Calculation.model_validate(spec)
                valid = True
            except (ValueError, TypeError):
                valid = False
        else:
            valid = bool(binding) and binding_allowed(binding)
        result['matched' if valid else 'pending'].append(field['id'])
    return result
