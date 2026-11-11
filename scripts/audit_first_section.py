"""Reproduce numeric comparisons for the October report's first major section."""
from __future__ import annotations
import json, re, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import DATA
from app.ooxml import read_docx, read_xlsx
from app.storage import Store

TASK_ID = '9720f37ef9d646c8b81655c2d0a73afb'
report = read_docx(ROOT / '2026年10月安顺市网络舆情分析报告.docx')
blocks = {b['index']: b['text'] for b in report['blocks']}
task = Store(DATA).get_task(TASK_ID)
metrics = Store(DATA).get_artifact(task.result_refs['calculate_metrics'])
dedup = read_xlsx(ROOT / '安顺市委10月负面预警数据（已去重）.xlsx', sheet_index=3)
rows = dedup['rows'][1:]
assert dedup['rows'][0]['cells'][:3] == ['标题', '区县', '事件分类']
total = metrics['record_count']
checks = []

def check(field, actual, paragraph, pattern, expected_text=None):
    found = re.search(pattern, blocks[paragraph])
    expected = expected_text if expected_text is not None else str(actual)
    checks.append({'field': field, 'computed': actual, 'report': found.group(1) if found else None,
                   'match': bool(found and found.group(1) == expected)})

check('all_record_count_wan', round(total / 10000, 2), 17, r'约([\d.]+)万余条', f'{total / 10000:.2f}')
for label in ('正面', '中性', '负面'):
    count = metrics['sentiment'][label]
    check(f'{label}_count', count, 17, label + r'(\d+)条')
    check(f'{label}_pct', round(count / total * 100, 2), 17,
          label + r'\d+条，占([\d.]+)%', f'{count / total * 100:.2f}')
check('peak_day', metrics['peak_day'], 17, r'信息峰值在(\d+月\d+日)',
      f'{int(metrics["peak_day"][5:7])}月{int(metrics["peak_day"][8:10])}日')
for label, count in metrics['platform'].items():
    check(f'platform_{label}_count', count, 26, re.escape(label) + r'(\d+)条')
    check(f'platform_{label}_pct', round(count / total * 100, 2), 26,
          re.escape(label) + r'\d+条，占([\d.]+)%', f'{count / total * 100:.2f}')
check('deduplicated_warning_count_a', len(rows), 17, r'重点预警数据(\d+)条')
check('deduplicated_warning_pct', round(len(rows) / total * 100, 2), 17,
      r'重点预警数据\d+条占([\d.]+)%', f'{len(rows) / total * 100:.2f}')
check('deduplicated_negative_count_d', len(rows), 30, r'敏感及负面舆情(\d+)条')
categories = Counter(r['cells'][2] for r in rows)
check('traffic_category_pct', round(categories['交通管理'] / len(rows) * 100, 2), 30,
      r'交通管理类信息占比约([\d.]+)%', f'{categories["交通管理"] / len(rows) * 100:.2f}')
localities = Counter(r['cells'][1] for r in rows)
for label, count in localities.items():
    check(f'locality_{label}_count', count, 30, re.escape(label) + r'(\d+)条')
    check(f'locality_{label}_pct', round(count / len(rows) * 100, 2), 30,
          re.escape(label) + r'\d+条，占比([\d.]+)%', f'{count / len(rows) * 100:.2f}')
output = {'source_report': '2026年10月安顺市网络舆情分析报告.docx',
          'source_all_records': '安顺市委10月总数据.xlsx',
          'source_deduplicated': '安顺市委10月负面预警数据（已去重）.xlsx',
          'scope': 'first major section numeric fields with unambiguous workbook lineage',
          'matched': sum(c['match'] for c in checks), 'total': len(checks),
          'accuracy': sum(c['match'] for c in checks) / len(checks),
          'deduplicated_rows_flagged_repeat': sum(r['cells'][4] == '是' for r in rows),
          'checks': checks}
destination = DATA / 'first-section-audit.json'
destination.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'matched': output['matched'], 'total': output['total'],
                  'accuracy': output['accuracy'],
                  'mismatches': [x['field'] for x in checks if not x['match']],
                  'artifact': str(destination)}, ensure_ascii=True))
