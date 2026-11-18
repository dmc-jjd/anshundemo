"""Deterministic field calculations, separate from model orchestration."""
from ..frozen_report import Calculation

# Explicit definitions for the existing confirmed monthly template. New semantic
# fields use the same typed catalog through the planner, never guessed numbers.
KNOWN={
 'b5_issue_no':{'metric':'issue_number'},'b8_publish_month':{'metric':'publish_month'},'b8_publish_day':{'metric':'publish_day'},
 'b12_report_month':{'metric':'report_month'},'b26_month':{'metric':'report_month'},'b29_report_month':{'metric':'report_month'},
 'b17_total_volume':{'metric':'scaled_count'},'b17_peak_date':{'metric':'peak_date'},
 'b17_warning_count':{'metric':'count','scope':'confirmed_events'},'b17_warning_ratio':{'metric':'warning_percentage','scope':'confirmed_events'},
 'b17_top_negative_categories':{'metric':'category_names','scope':'confirmed_events'},
 'b26_platform_rank_list':{'metric':'platform_names'},'b26_platform_entries':{'metric':'platform_statistics'},'b26_key_platform_list':{'metric':'platform_names'},
 'b30_negative_total':{'metric':'count','scope':'confirmed_events'},'b30_top_category_with_share':{'metric':'leading_category','scope':'confirmed_events'},
 'b30_county_distribution_list':{'metric':'county_statistics','scope':'confirmed_events'},'b34_top10_table':{'metric':'top10'},
 'b26_main_channels':{'metric':'platform_names'},'b32_figure_no':{'metric':'constant','value':'4'},'b35_table_no':{'metric':'constant','value':'1'}}
for name,sentiment in [('positive','正面'),('neutral','中性'),('negative','负面')]:
    KNOWN['b17_'+name+'_count']={'metric':'sentiment_count','sentiment':sentiment}
    KNOWN['b17_'+name+'_ratio']={'metric':'sentiment_percentage','sentiment':sentiment}

def calculation_for(field,report,plans,package=None,*,spec_resolver):
    spec=plans.get(field['id']) or KNOWN.get(field['id']) or spec_resolver(field,package)
    if spec:
        spec=Calculation.model_validate(spec).model_dump()
        if field['id'] in ('b17_warning_count','b17_warning_ratio'):spec['scope']=report.warning_scope()
        return report.calculate(spec)
    binding=field.get('binding') or {}
    if binding.get('tool')=='top10_events':return report.calculate({'metric':'top10'})
    if binding.get('tool')=='calculate_metrics':
        value=report.metrics
        for part in binding['path']:value=value[part]
        return {'value':str(value),'source_refs':[report.fact_ref],'calculation':binding}
    raise ValueError('缺少计算定义；请指定该字段的统计口径。')

def data_values(template,report,plans=None,package=None,*,calculate,validate):
    values={};issues=[]
    for field in template['fields']:
        if field['owner']!='data':continue
        try:
            result=calculate(field,report,plans or {},package=package)
            value={k:result[k] for k in ('value','source_refs')}
            validate(template,{field['id']:value},{report.fact_ref,report.state.metadata.get('report_parameters_ref')})
            values[field['id']]=value
        except Exception as exc:issues.append({'field_id':field['id'],'semantic':field.get('display_name',field['id']),'message':str(exc)[:600],'error':type(exc).__name__})
    return values,issues

