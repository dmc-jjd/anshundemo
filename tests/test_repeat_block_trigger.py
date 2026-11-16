"""可变列表（repeat block）触发条件：从「工作建议」泛化到结构判据。

五条判据：
1. 安顺版式（含「（二）工作建议」标题）仍走原路径，repeat 只出现一次且字段不变；
2. 龙川版式（「三、下一步关注重点」）走新结构判据，两个子项各编译成一个 repeat；
3. 标题后不足 3 条编号段落 → 不触发（普通编号列表不被误伤）；
4. 序号归属统一：编号留在固定文字里，字段值不再吞序号；
5. repeat 条数是 4..6 的区间，不是写死的 5。
"""
from __future__ import annotations

import asyncio
import re

from app.structured_template import build_structured_template
from app.template_compare import compare_reports
from app.template_review import compile_review, make_input
from test_structured_template import docx, semantic_analyst

NUMBERED = re.compile(r'^\s*\d+[.、．]')


def documents(tmp_path, specimens):
    return [docx(tmp_path / f'report{position}.docx', '</w:t></w:r></w:p><w:p><w:r><w:t>'.join(paragraphs))
            for position, paragraphs in enumerate(specimens)]


def compile_template(docs, analyst=semantic_analyst):
    local = build_structured_template(docs, 'comparison')
    packet = make_input(docs, compare_reports(docs), local)
    indexes = [block['index'] for block in packet['source_reports'][0]['blocks']]
    result = asyncio.run(analyst('template_analyst', {**packet, 'target_blocks': indexes}))
    return compile_review(result, packet, 'comparison')


def instance_naming_analyst(role, payload):
    """模拟真实模型：编号条目按当期主题命名（正是要消掉的实例化命名）。"""
    async def run():
        result = await semantic_analyst(role, payload)
        for field in result['fields']:
            text = field['sources'][0]['text']
            if NUMBERED.match(text):
                field['display_name'] = text[:10] + '风险细节'
        return result
    return run()


def advice_specimen(position):
    """安顺版式：先有一组普通编号列表，再有「（二）工作建议」编号建议。"""
    return ['一、舆情特点', '（一）信息走势',
            f'1.甲{position}走势；', f'2.乙{position}走势；', f'3.丙{position}走势；',
            '（二）工作建议',
            f'1.建议甲{position}。', f'2.建议乙{position}。', f'3.建议丙{position}。']


def focus_specimen(position):
    """龙川版式：「三、下一步关注重点」两个子项，每项导语 + 5 条编号条目。"""
    paragraphs = ['三、下一步关注重点', f'（一）关注甲{position}类舆情风险',
                  f'导语甲{position}，各相关部门需重点警惕以下舆情细节：']
    paragraphs += [f'{number}.甲{position}第{number}条风险细节；' for number in range(1, 6)]
    paragraphs += [f'（二）关注乙{position}类舆情风险',
                   f'导语乙{position}，各相关单位需重点警惕以下舆情细节：']
    paragraphs += [f'{number}.乙{position}第{number}条风险细节。' for number in range(1, 6)]
    return paragraphs


def short_specimen(position):
    """标题之后只有 2 条编号段落：普通编号列表，不该变成 repeat。"""
    return ['三、下一步关注重点', f'（一）关注甲{position}类舆情风险',
            f'导语{position}，需警惕以下细节：', f'1.甲{position}第一条；', f'2.乙{position}第二条。']


def test_anshun_work_advice_path_is_unchanged_and_absorbs_nothing_else(tmp_path):
    template = compile_template(documents(tmp_path, [advice_specimen(i) for i in range(3)]))
    repeats = [block for block in template['blocks'] if block['kind'] == 'repeat']
    assert len(repeats) == 1
    assert repeats[0]['source_block_indexes'] == [6, 7, 8]
    fields = {field['id']: field for field in template['fields']}
    advice = fields['monthly_recommendations']
    assert advice['kind'] == 'paragraph_list' and advice['owner'] == 'writer'
    assert advice['display_name'] == '前瞻风险与工作建议（4—5类）'
    assert advice['value_schema']['minItems'] == 4 and advice['value_schema']['maxItems'] == 5
    # 前面那组 3 条普通编号列表没有被新判据吞掉。
    assert all(index in {block['index'] for block in template['blocks']} for index in (0, 1, 2, 3, 4, 5))


def test_focus_section_compiles_two_repeat_blocks_with_positional_names(tmp_path):
    template = compile_template(documents(tmp_path, [focus_specimen(i) for i in range(3)]),
                                instance_naming_analyst)
    repeats = [block for block in template['blocks'] if block['kind'] == 'repeat']
    assert len(repeats) == 2
    assert [block['source_block_indexes'] for block in repeats] == [[3, 4, 5, 6, 7], [10, 11, 12, 13, 14]]
    assert len(template['fields']) == 7               # 2 标题 + 2 导语 + 2 repeat + 1 章标题
    names = [field['display_name'] for field in template['fields']]
    assert '编号条目列表（第1组）' in names and '编号条目列表（第2组）' in names
    # 被 repeat 吸收的条目字段（及其按当期主题起的名字）全部消失。
    assert not any('甲0' in name or '乙0' in name for name in names)
    assert not any(re.match(r'^b(?:3|4|5|6|7|10|11|12|13|14)_', field['id'])
                   for field in template['fields'])


def test_short_numbered_list_stays_a_plain_list(tmp_path):
    template = compile_template(documents(tmp_path, [short_specimen(i) for i in range(3)]))
    assert not any(block['kind'] == 'repeat' for block in template['blocks'])
    assert len(template['fields']) == 5


def test_ordinal_belongs_to_fixed_text_not_to_the_field_value(tmp_path):
    template = compile_template(documents(tmp_path, [short_specimen(i) for i in range(3)]))
    fields = {field['id']: field for field in template['fields']}
    numbered = [block for block in template['blocks']
                if block['kind'] == 'paragraph' and block['parts']
                and 'text' in block['parts'][0] and NUMBERED.match(block['parts'][0]['text'])]
    assert [block['parts'][0]['text'] for block in numbered] == ['1.', '2.']
    for block in numbered:
        assert len(block['parts']) == 2 and 'field' in block['parts'][1]
        field = fields[block['parts'][1]['field']]
        assert not NUMBERED.match(field['sources'][0]['text'])   # 序号已剥回固定文字
        assert not (len(block['parts']) == 1 and 'field' in block['parts'][0])


def test_repeat_item_bounds_are_a_range_not_a_fixed_count(tmp_path):
    template = compile_template(documents(tmp_path, [focus_specimen(i) for i in range(3)]))
    for block in template['blocks']:
        if block['kind'] != 'repeat':
            continue
        field = next(item for item in template['fields'] if item['id'] == block['parts'][0]['field'])
        assert field['value_schema']['minItems'] == 4
        assert field['value_schema']['maxItems'] == 6
        assert field['value_schema']['maxItems'] != 5
        assert len(field['sources']) == 15          # 5 条 × 3 份报告


# 三块分批已取消（整份模板一次调用）：原「同批不混编号条目」的断言随分批机制一起删除，
# 现在的单次调用契约由 tests/test_template_single_shot.py 钉住。
