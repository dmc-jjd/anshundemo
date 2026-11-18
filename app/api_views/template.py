import copy
import hashlib
from pathlib import Path

REPORT_SUFFIXES = ('.docx', '.doc', '.xlsx')


def strip_report_suffix(name):
    """去掉报告文件扩展名与首尾空白；`（文成县委）` 这类区域前缀是用户的命名习惯，保留。"""
    text = str(name or '').strip()
    lowered = text.lower()
    for suffix in REPORT_SUFFIXES:
        if lowered.endswith(suffix):
            return text[:-len(suffix)].strip()
    return text


def resolve_template_name(uploads, file_ids, requested):
    """模板名：用户填的优先；缺省时取第一份上传文件的文件名（去后缀）。

    `template_name` 是用户在模板确认页可编辑的默认值，所以这里只做「没想到用哪个」的兜底：
    请求体没带就按上传顺序找第一份记得住原始文件名的文件，找不到返回空串（显示名回退旧口径）。
    """
    text = str(requested or '').strip()
    if text:
        return text
    from ..upload_names import lookup
    for file_id in file_ids or []:
        name = strip_report_suffix(lookup(uploads, file_id))
        if name:
            return name
    return ''


async def template_name_from_request(request):
    """从原始请求体里取 `template_name`（`TaskCreate` 不含这个字段：加它会让 G-OPENAPI 移动）。

    FastAPI 已经把请求体读进 `Request` 缓存，这里再读一次拿到的是同一份字节，不会吞掉请求体。
    取不到就返回 None，由 `resolve_template_name` 退回「第一份上传文件名」。
    """
    try:
        payload = await request.json()
    except (ValueError, TypeError, RuntimeError):
        return None
    return payload.get('template_name') if isinstance(payload, dict) else None


def apply_top10_rule_preserving(definition):
    """`apply_top10_rule` 会无条件重写该字段的显示名/语义；人工改过的键不能被它盖回去。

    候选模板每次 GET 与 confirm 都会跑一遍 TOP10 规则，用户的编辑就会表现为
    「保存成功、刷新后又变回去」。这里先把带人工标记（`human_edited`）的键记下来，
    跑完规则再写回——规则口径里其余部分（表头、绑定、值 schema）照旧生效。
    """
    from ..structured_template import apply_top10_rule
    edited = {}
    for field in definition.get('fields') or []:
        keys = [key for key in field.get('human_edited') or [] if key in ('display_name', 'semantic', 'rule', 'reason', 'format')]
        if keys:
            edited[field['id']] = {key: field[key] for key in keys if key in field}
    result = apply_top10_rule(definition)
    if edited:
        for field in result.get('fields') or []:
            field.update(edited.get(field['id']) or {})
    return result


def definition_with_charts(definition):
    """模板定义 + 图表实例列表；返回 (error, definition)，error=(status,detail) 由路由转 HTTP。

    `.doc`（Word 97-2003）基准报告没有 OOXML 版式：`definitions` 的图表清单本身来自客户包
    registry，只有「图形数量」取决于版式，所以这里降级为空并标记 `layout_available=False`，
    让模板确认页照常加载块/字段。坏 ZIP 是另一回事——它是真错误，按 422 交回可指导文案。
    行为判据只在 `.doc` 上多一个键：`.docx` 的返回体逐字不变。
    """
    from ..chart_spec import definitions, layout_available
    try:
        definition['charts'] = definitions(definition)
    except ValueError as exc:
        return (422, str(exc)), definition
    if not layout_available(definition):
        definition['layout_available'] = False
    return None, definition


def apply_definition_patch(store, state, req):
    """模板定义补丁。返回 (error, result)：error=(status,detail) 由路由函数转成 HTTP 错误。"""
    from ..structured_template import revise_candidate
    if state.revision!=req.expected_revision: return (409,'stale_template_revision'),None
    if state.metadata.get('confirmed_template_ref'): return (409,'immutable_confirmed_template'),None
    ref=state.metadata.get('structured_template_ref')
    if not ref: return (404,'structured_template_missing'),None
    if not state.metadata.get('template_validation_ref'):return (409,'template_semantic_review_required'),None
    if any(set(patch)-{'display_name'} for patch in req.fields.values()):return (422,'semantic_changes_require_model_review'),None
    try:
        candidate=revise_candidate(store.get_artifact(ref),req.fields)
        if req.chart_styles is not None:
            from ..chart_spec import with_styles
            candidate=with_styles(candidate,req.chart_styles)
        if req.rules is not None:
            candidate['rules']=rules_for_features(req.rules,candidate.get('rules'))
    except ValueError as exc: return (422,str(exc)),None
    from ..template_draft import current_draft, rebuild, _log_entries, DRAFT_KIND, DraftError
    draft = current_draft(store, state)
    rebased = None
    if draft:
        if draft.get('base_ref') != ref:
            return (409, 'stale_template_candidate'), None
        try:
            rebased = rebuild(candidate, _log_entries(draft), '', draft.get('field_edits'))
        except DraftError as exc:
            return (exc.status, exc.code), None
    state.metadata['structured_template_ref']=store.put_artifact(state.id,'structured_template_candidate',candidate)
    if rebased is not None:
        rebased['base_ref'] = state.metadata['structured_template_ref']
        state.metadata['manual_template_draft_ref'] = store.put_artifact(state.id, DRAFT_KIND, rebased)
    from ..template_review import digest
    validation=store.get_artifact(state.metadata['template_validation_ref'])
    validation.update(candidate_ref=state.metadata['structured_template_ref'],candidate_hash=digest(candidate))
    state.metadata['template_validation_ref']=store.put_artifact(state.id,'template_validation',validation)
    store.put_task(state,state.revision)
    return None,None


MANUAL_POLICY_VERSION = 'MANUAL-1'
MANUAL_SOURCE = 'manual_definition'

#: 模板级「跑不跑」开关（与 `rules.event_threshold` 同级，随 template_version 一起存）。
#: 语义分工：`review_service.check_rules` 管**口径**（阈值/范围/排序），这里管**步骤开不开**。
#: 缺省一律 True —— 未写这些键的老模板行为逐字节不变。
#: `first_warning` / `top10` 是同一套机制的扩项：关掉后对应段落**不生成**（不是留空）。
PROCESSING_FEATURES = ('dedup', 'classification', 'first_warning', 'top10')

#: 关掉开关后要「整段不生成」的判定面。
#: 不按字段 id 判——id 由模型/人工生成（实测是 `b34_top10_rows` 这类不稳定名）；按语义面判：
#:   * `tools`：字段的取数绑定（TOP10 表的绑定恒为 `top10_events`）；
#:   * `markers`：显示名/语义里的关键词（`top10` 用小写比较；`重点预警` 是原文口径词）；
#:   * `text`：**纯文字块**里的关键词——TOP10 的表题注（`表1 …TOP10`）没有字段，只能按文字认；
#:   * `rules`：随开关一起消失的统计口径键（关掉的口径不该继续写进模板版本）。
OMISSION_RULES = {
    'first_warning': {'tools': (), 'markers': ('重点预警',), 'text': (), 'rules': ('first_warning_scope',)},
    'top10': {'tools': ('top10_events',), 'markers': ('top10',), 'text': ('top10',),
              'rules': ('ranking', 'top10_scope', 'top10_unit', 'top10_display', 'summary_min_chars',
                        'summary_max_chars')},
}

#: 句子/分句边界：定位「这个字段的引导语从哪儿开始」。
_CLAUSE_BOUNDARY = '。！？；，、：'


def _raw_features(source):
    value = source.get('features') if isinstance(source, dict) else None
    return value if isinstance(value, dict) else None


def normalize_features(rules, stored=None):
    """取出模板的四个处理开关；未声明或脏值一律当 `True`（不静默关掉客户流程）。

    `stored` 是候选/已确认版本里已存的 rules：界面只提交口径（不带 `features`）时，
    已保存的开关键不能被这次提交抹回默认值。
    """
    current = _raw_features(rules) or _raw_features(stored) or {}
    return {name: current.get(name) is not False for name in PROCESSING_FEATURES}


def rules_for_features(rules, stored=None):
    """口径 + 开关一起归一：关掉的口径键不写进模板版本（`check_rules` 仍管其余校验）。

    `check_rules` 要求 `first_warning_scope` / `ranking` 必填。开关关掉时界面提交的是空值，
    所以先用合法占位值过校验，再把该口径连同它的派生键一起删掉——口径既然关掉，
    就不该留在已确认版本里被下游当成「用户选过」。
    """
    from ..review_service import check_rules
    features = normalize_features(rules, stored)
    effective = dict(rules) if isinstance(rules, dict) else {}
    # 界面在开关关掉时提交的是空串，`check_rules` 会拒；先补合法占位值过校验，随后整键删掉。
    if features['first_warning'] is False and not effective.get('first_warning_scope'):
        effective['first_warning_scope'] = 'negative_or_warning'
    if features['top10'] is False and not effective.get('ranking'):
        effective['ranking'] = 'negative_warning_member_count'
    result = check_rules(effective)
    for feature, rule in OMISSION_RULES.items():
        if features[feature] is not False:
            continue
        for key in rule['rules']:
            result.pop(key, None)
    result['features'] = features
    return result


def _active_omissions(features):
    return [(feature, rule) for feature, rule in OMISSION_RULES.items() if features.get(feature) is False]


def _field_matches(field, rule):
    binding = field.get('binding') or {}
    tool = binding.get('tool')
    if tool and tool in rule['tools']:
        return True
    if binding.get('metric')=='top10' and 'top10_events' in rule.get('tools', ()):
        return True
    text = ' '.join(str(field.get(key) or '') for key in ('display_name', 'semantic')).lower()
    return any(marker.lower() in text for marker in rule['markers'])


def omitted_field_ids(definition, features):
    """关掉开关后不再产出的字段 id（判定见 `OMISSION_RULES`）。"""
    dropped = set()
    for _feature, rule in _active_omissions(features):
        dropped.update(field['id'] for field in definition.get('fields') or [] if _field_matches(field, rule))
    return dropped


def _block_visible_text(block):
    return ''.join(part.get('text', '') for part in block.get('parts') or [] if 'text' in part)


def _span_segments(block, fields):
    """把一块的 parts 摊平成 `[(kind, value, length)]`，同时给出原段落全文。"""
    segments = []
    for part in block.get('parts') or []:
        if 'text' in part:
            segments.append(('text', part['text'], len(part['text'])))
            continue
        key = part['field']
        source = (fields.get(key) or {}).get('sources') or [{}]
        length = len(source[0].get('text') or '')
        segments.append(('field', key, length))
    return segments


def _span_ranges(full, segments, dropped):
    """被关掉的字段要删掉的字符区间。

    只删字段本身会留下「负面单一重点预警数据」这类引导语，段落读不通。两级判：
    * 整句里没有别的存活字段 → 删整句（`其中，安顺涉〔类别〕问题发布较多（详见表1）。`
      这类只服务 TOP10 的引导句，留下会指向一张已不存在的表）；
    * 整句里还有别的字段 → 只删「引导语 + 字段 + 紧随的括注」（重点预警那句里还有类别清单）。
    """
    spans = []
    cursor = 0
    for kind, value, length in segments:
        if kind == 'field':
            spans.append((value, cursor, cursor + length))
        cursor += length
    survivors = [(start, end) for key, start, end in spans if key not in dropped]
    ranges = []
    for key, start, end in spans:
        if key not in dropped:
            continue
        sentence_start = start
        while sentence_start > 0 and full[sentence_start - 1] not in '。！？':
            sentence_start -= 1
        sentence_end = end
        while sentence_end < len(full) and full[sentence_end] not in '。！？':
            sentence_end += 1
        if sentence_end < len(full) and full[sentence_end] in '。！？':
            sentence_end += 1
        if not any(a < sentence_end and sentence_start < b for a, b in survivors):
            ranges.append((sentence_start, sentence_end))
            continue
        head = start
        while head > 0 and full[head - 1] not in _CLAUSE_BOUNDARY:
            head -= 1
        tail = end
        if full[tail:tail + 1] == '（':
            close = full.find('）', tail)
            if close != -1:
                tail = close + 1
                if full[tail:tail + 1] in ('，', '；'):
                    tail += 1
        ranges.append((head, tail))
    return ranges


def _cut(text, ranges):
    """按区间删除字符；返回 (新全文, 老偏移 → 新偏移)。"""
    keep = [True] * len(text)
    for start, end in ranges:
        for position in range(max(0, start), min(len(text), end)):
            keep[position] = False
    mapping = {}
    kept = []
    for position, char in enumerate(text):
        mapping[position] = len(kept)
        if keep[position]:
            kept.append(char)
    mapping[len(text)] = len(kept)
    return ''.join(kept), mapping


def _rebuild_parts(new_text, placed):
    """按保留下来的字段位置重排 parts（文本段 + 字段占位，偏移与新版式逐字对齐）。"""
    parts = []
    cursor = 0
    for key, start, length in placed:
        if start > cursor:
            parts.append({'text': new_text[cursor:start]})
        parts.append({'field': key})
        cursor = start + length
    if cursor < len(new_text):
        parts.append({'text': new_text[cursor:]})
    return [part for part in parts if part.get('text') != '' or 'field' in part]


def _removed_ranges(keep):
    """布尔掩码 → 半开区间列表：渲染期按区间删字，比把整份掩码存进模板版本省体积。"""
    ranges = []
    for position, kept in enumerate(keep):
        if kept:
            continue
        if ranges and ranges[-1][1] == position:
            ranges[-1][1] = position + 1
        else:
            ranges.append([position, position + 1])
    return ranges


def omit_disabled_sections(definition, features):
    """关掉的开关 → 模板里这些字段/整段不再产出（默认全开时原样返回，零行为变化）。

    三种落法：
    * 整块（表格行、重复块）字段被关 → 整块从模板去掉并在渲染期删段（TOP10 表）；
    * 段落内字段被关 → 只删「引导语 + 字段 + 括注」这段字符，同段其余字段照旧（重点预警句）；
    * 纯文字块点名被关的段落 → 整块去掉（`表1 …TOP10` 题注没有字段）。

    版式**不做副本**：删哪些块、哪些字符区间都记进 `omitted_sections`，
    `render_structured_docx` 渲染时照单删掉，`layout_source` 始终指回原始版式。
    块索引也因此保持原始偏移，不再需要按删除数重排。
    """
    active = _active_omissions(features)
    if not active:
        return definition
    result = copy.deepcopy(definition)
    fields = {field['id']: field for field in result.get('fields') or []}
    dropped = omitted_field_ids(result, features)
    blocks = result.get('blocks') or []
    drop_blocks = set()
    paragraph_edits = {}
    for block in blocks:
        index = block['index']
        referenced = [part['field'] for part in block.get('parts') or [] if 'field' in part]
        hits = [key for key in referenced if key in dropped]
        kind = block.get('kind')
        if kind in ('table', 'repeat'):
            if hits:
                drop_blocks.add(index)
            continue
        if not hits:
            text = _block_visible_text(block).lower()
            if referenced:
                continue
            if any(marker.lower() in text for _feature, rule in active for marker in rule['text']):
                drop_blocks.add(index)
            continue
        segments = _span_segments(block, fields)
        full = ''.join(
            value if kind == 'text'
            else (((fields.get(value) or {}).get('sources') or [{}])[0].get('text') or '')
            for kind, value, _length in segments)
        ranges = _span_ranges(full, segments, dropped)
        new_text, mapping = _cut(full, ranges)
        placed = []
        cursor = 0
        for kind, value, length in segments:
            if kind == 'field' and value not in dropped:
                placed.append((value, mapping[cursor], length))
            cursor += length
        if not placed and not new_text.strip():
            drop_blocks.add(index)
            continue
        keep = [True] * len(full)
        for start, end in ranges:
            for position in range(max(0, start), min(len(full), end)):
                keep[position] = False
        removed = _removed_ranges(keep)
        if removed:
            paragraph_edits[index] = removed
        block['parts'] = _rebuild_parts(new_text, placed)
    if not drop_blocks and not paragraph_edits:
        return definition
    kept_blocks = [block for block in blocks if block['index'] not in drop_blocks]
    kept_fields = [field for field in result['fields'] if field['id'] not in dropped]
    from ..structured_template import _schema
    result['blocks'] = kept_blocks
    result['fields'] = kept_fields
    result['output_schema'] = _schema(kept_fields)
    result['writer_schema'] = _schema(kept_fields, True)
    for feature, rule in active:
        for key in rule['rules']:
            if key in ('first_warning_scope', 'ranking'):
                continue
            result.pop(key, None)
    result['omitted_sections'] = {
        'features': [feature for feature, _rule in active],
        'fields': sorted(dropped),
        'blocks': sorted(drop_blocks),
        # 渲染期删字用的字符区间（半开区间）；键是原始版式里的块下标。
        'paragraph_edits': {str(index): ranges for index, ranges in sorted(paragraph_edits.items())},
        'source_layout': (definition.get('source_reports') or [{}])[0],
        # 标记「本模板的版式是原始文件，删段在渲染期做」。老模板（派生版式）没有这个标记，
        # 渲染路径保持不变，避免按原始下标去删派生版式里的段。
        'render_trim': True,
    }
    return result


def manual_validation(store, state, candidate_ref, candidate):
    """手工定义草稿 → (合成 validation, 生效候选)；不满足条件返回 (None, None)。

    这是**并列入口**，不是放宽模型研判：只有「草稿确实是这份候选的完整重放」时才合成一条
    `source=manual_definition` / `policy_version=MANUAL-1` 的 validation，之后 confirm 的全部
    校验（candidate_hash / candidate_ref / input_ref / input_hash / review_refs、来源报告、
    业务问题、规则）照旧逐条执行。草稿不完整或不是基于这份候选时不合成，原逻辑原样生效。
    """
    from ..template_draft import current_draft
    from ..template_review import digest
    draft = current_draft(store, state)
    if not draft or draft.get('base_ref') != candidate_ref:
        return None, None
    if [b['index'] for b in draft.get('blocks') or []] != [b['index'] for b in candidate.get('blocks') or []]:
        return None, None
    draft_fields = {field['id'] for field in draft.get('fields') or []}
    removed = {fid for entry in draft.get('selection_log') or []
               for fid in entry.get('removed_fields') or []}
    # 候选的每个字段都必须有着落：仍在草稿里，或被这条手动定义显式改回固定文字。
    if any(field['id'] not in draft_fields and field['id'] not in removed
           for field in candidate.get('fields') or []):
        return None, None
    input_ref = state.metadata.get('template_input_ref')
    if not input_ref:
        return None, None
    from ..structured_template import _schema
    effective = {**candidate, 'blocks': draft['blocks'], 'fields': draft['fields']}
    effective['output_schema'] = _schema(effective['fields'])
    effective['writer_schema'] = _schema(effective['fields'], True)
    validation = {
        'validation': 'passed', 'source': MANUAL_SOURCE,
        'candidate_hash': digest(effective), 'candidate_ref': candidate_ref,
        'policy_version': MANUAL_POLICY_VERSION, 'input_ref': input_ref,
        'input_hash': digest(store.get_artifact(input_ref)),
        'review_refs': [state.metadata.get('manual_template_draft_ref')],
        'manual_log': draft.get('selection_log') or [],
    }
    return validation, effective


def confirm_candidate(store, state, req):
    """人工确认模板候选。返回 (error, state)：已确认过则原样返回 state。"""
    if state.kind!='template': return (422,'not_template_task'),None
    if state.revision!=req.expected_revision: return (409,'stale_task_revision'),None
    if state.metadata.get('confirmed_template_ref'):return None,state
    if state.phase!='awaiting_template_confirmation':return (409,'template_semantic_review_required'),None
    if not state.metadata.get('comparison_ref'): return (409,'comparison_missing'),None
    if not state.metadata.get('structured_template_ref'): return (409,'structured_template_missing'),None
    if req.candidate_ref!=state.metadata['structured_template_ref']:return (409,'stale_template_candidate'),None
    candidate=store.get_artifact(state.metadata['structured_template_ref'])
    from ..template_review import digest,POLICY_VERSION
    manual,effective=manual_validation(store,state,state.metadata['structured_template_ref'],candidate)
    if manual is not None:
        # 生效候选 = 草稿的 blocks/fields（用户看到的就是它）；validation 随之重算。
        candidate=effective
        state.metadata['template_validation_ref']=store.put_artifact(state.id,'template_validation',manual)
    validation_ref=state.metadata.get('template_validation_ref')
    if not validation_ref:return (409,'template_semantic_review_required'),None
    validation=store.get_artifact(validation_ref)
    # 入口来源只决定 policy_version 的取值：手工入口只认本次刚合成的 MANUAL-1，
    # 模型研判入口仍然只认 POLICY_VERSION。
    manual_source=validation.get('source')==MANUAL_SOURCE
    if manual_source and manual is None:return (409,'template_semantic_review_required'),None
    policy=MANUAL_POLICY_VERSION if manual_source else POLICY_VERSION
    if (validation.get('validation')!='passed' or validation.get('candidate_hash')!=digest(candidate)
        or validation.get('candidate_ref')!=req.candidate_ref or validation.get('policy_version')!=policy
        or validation.get('input_ref')!=state.metadata.get('template_input_ref')
        or validation.get('input_hash')!=digest(store.get_artifact(validation['input_ref']))
        or not validation.get('review_refs')):return (409,'template_semantic_review_required'),None
    if any(hashlib.sha256(Path(s['path']).read_bytes()).hexdigest()!=s['sha256'] for s in candidate['source_reports']):
        return (409,'template_source_changed'),None
    for item in state.review_items:
        if item['kind']=='template_business_question' and item['status']!='resolved':
            answer=req.resolutions.get(item['id'],'').strip()
            if not answer:return (409,'unresolved_template_review'),None
            item.update(status='resolved',decision={'action':'confirm','answer':answer,'reason':req.reason})
    if any(x['blocking'] and x['status']!='resolved' and x['kind']!='template_candidate' for x in state.review_items): return (409,'unresolved_template_review'),None
    # 开关先定：关掉 top10 就**不执行** TOP10 规则（它会无条件把表头/语义/绑定重写回模板），
    # 并且把该段从模板里去掉、在渲染期删段；关掉 first_warning 同理去掉重点预警口径与字段。
    # 版式不做副本：`layout_source` 始终指回原始版式，删段记录在 `omitted_sections`。
    try:
        candidate['rules']=rules_for_features(req.rules or candidate.get('rules'),candidate.get('rules'))
    except (ValueError,TypeError) as exc:return (422,str(exc)),None
    features=candidate['rules']['features']
    if features['top10']:
        candidate=apply_top10_rule_preserving(candidate)
    else:
        candidate.pop('top10_rule',None)
    candidate=omit_disabled_sections(candidate,features)
    for item in state.review_items:
        if item['kind']=='template_candidate':item.update(status='resolved',decision={'action':'confirm','reason':req.reason})
    business_decisions=[{'question':i['question'],'answer':i.get('decision',{}).get('answer') or i.get('decision',{}).get('payload',{}).get('answer','')} for i in state.review_items if i['kind']=='template_business_question']
    ref=store.put_artifact(state.id,'template_version',{**candidate,'version':1,'status':'confirmed_by_human','name':str(state.metadata.get('template_name') or '').strip(),'model_analysis':state.metadata.get('model_analysis'),'source_file_ids':state.input_refs,'human_reason':req.reason,'template_validation_ref':validation_ref,'human_resolutions':req.resolutions,'business_decisions':business_decisions})
    state.metadata['confirmed_template_ref']=ref; state.phase='template_confirmed'; store.put_task(state,state.revision)
    store.append_event(state.id,{'type':'template_confirmed','template_ref':ref,'reason':req.reason})
    return None,state
