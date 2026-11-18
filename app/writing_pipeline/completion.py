"""Template completion policy independent of persistence and approval."""
def preview_status(template, values, charts, *, count_charts):
    # Use the same explicit required contract as final validate_values.
    required=(template or {}).get('output_schema',{}).get('required')
    missing=[f['id'] for f in (template or {}).get('fields',[]) if f['id'] not in (values or {}) and (required is None or f['id'] in required)]
    pending=count_charts(template or {}, charts)
    return {'missing_fields':missing,'pending_charts':pending,'preview_only':bool(missing or pending)}

