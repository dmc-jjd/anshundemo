"""Generic frozen-record aggregations. Client vocabulary belongs in bindings."""
from collections import Counter
from datetime import date


def _text(value):
    return '' if value is None else str(value).strip()


def _rows(report, spec):
    from .frozen_report import MissingReportInput
    rows = report._scoped_records(spec)
    # Distinguish absent input columns from a valid filter returning zero rows.
    for key in spec.filters:
        if rows and not any(_text(row.get(key)) for row in rows):
            raise MissingReportInput('冻结记录缺少可用筛选列：' + key)
    return [row for row in rows if all(_text(row.get(key)) in values for key, values in spec.filters.items())]


def calculate(report, spec):
    from .frozen_report import MissingReportInput
    metric = spec.metric
    if metric == 'parameterized_table':
        parameters = report.parameters()
        from string import Formatter
        required = {key for row in spec.rows for cell in row
                    for _, key, _, _ in Formatter().parse(cell) if key is not None}
        values = {}
        for key in required:
            value = parameters.get(key)
            if value is None or not _text(value):
                raise MissingReportInput('表格缺少本期参数：' + key)
            if key == 'publication_date':
                day = date.fromisoformat(str(value))
                value = f'{day.year}年{day.month}月{day.day}日' if spec.date_format == 'chinese' else day.isoformat()
            values[key] = str(value)
        return [[cell.format_map(values) for cell in row] for row in spec.rows], None

    rows = _rows(report, spec)
    if metric == 'filtered_record_count':
        return str(len(rows)), None
    if metric in ('distinct_organization_count','organization_names'):
        from .media_identity import organization_counts
        counts=organization_counts(rows,spec.organization_aliases,spec.organization_suffixes)
        return (str(len(counts)) if metric=='distinct_organization_count' else '、'.join(list(counts)[:spec.limit])), None
    if metric == 'distinct_source_count':
        identities = set()
        for row in rows:
            primary = _text(row.get(spec.identity_field))
            fallback = tuple(_text(row.get(key)) for key in spec.identity_fallback)
            if primary:
                identities.add(('primary', primary))
            elif any(fallback):
                identities.add(('fallback', *fallback))
            else:
                raise MissingReportInput('记录缺少可辨识媒体身份：' + _text(row.get('id')))
        return str(len(identities)), None
    if metric == 'source_statistics':
        counts = Counter(_text(row.get('source')) or '未知' for row in rows)
        items = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:spec.limit]
        return '，'.join(f'{name}（{count}条）' for name, count in items) or '无记录', None
    if metric == 'peak_count':
        if not rows:
            return '0', None
        counts = report._daily_counts(rows)
        valid = {}
        for day, count in counts.items():
            try:
                date.fromisoformat(day)
            except ValueError:
                continue
            valid[day] = count
        if not valid:
            raise MissingReportInput('所选范围缺少有效日期，无法计算峰值条数。')
        return str(max(valid.values())), None
    if metric == 'selected_material_count':
        rows=[row for row in rows if all(any(term in ' '.join(_text(row.get(k)) for k in ('title','summary','author','source')) for term in group) for group in spec.selection_terms)]
        if spec.selection_title_terms:rows=[row for row in rows if any(term in _text(row.get('title')) for term in spec.selection_title_terms)]
        candidates = {_text(row.get('title')) for row in rows if _text(row.get('title'))}
        if not candidates:
            raise MissingReportInput('所选范围没有可用选题标题。')
        pool = report._scoped_records(spec)
        if spec.selection_terms:
            pool=[row for row in pool if all(any(term in ' '.join(_text(row.get(k)) for k in ('title','summary','author','source')) for term in group) for group in spec.selection_terms)]
        counts = Counter(_text(row.get('title')) for row in pool if _text(row.get('title')) in candidates)
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if spec.deduplicate_selection:
            from .tools.dedup import group_by_representative
            by_id={r['id']:r for r in rows}
            grouped=group_by_representative(rows,spec.selection_dedup_threshold)
            candidates_by_event=[]
            for group in grouped['groups']:
                titles={_text(by_id[rid].get('title')) for rid in group['member_ids']}
                lead=sorted(titles,key=lambda title:(-counts[title],title))[0]
                candidates_by_event.append((lead,sum(counts[t] for t in titles),titles))
            candidates_by_event.sort(key=lambda item:(-item[1],item[0]))
            title,count,titles=candidates_by_event[0]
            return str(count),{'title':title,'count':count,
                'record_refs':[row['id'] for row in pool if _text(row.get('title')) in titles],
                'candidates':[{'title':t,'count':n} for t,n,_ in candidates_by_event[:spec.limit]],
                'method':grouped['method']}
        title, count = ranked[0]
        return str(count), {'title': title, 'count': count,
                            'record_refs': [row['id'] for row in pool if _text(row.get('title')) == title],
                            'candidates': [{'title': key, 'count': n} for key, n in ranked[:spec.limit]]}
    raise ValueError('unsupported_extension_calculation:' + metric)
