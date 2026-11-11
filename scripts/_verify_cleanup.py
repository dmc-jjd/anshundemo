"""校验：4 个活跃任务的工件引用是否全部可解析。"""
import json, re, sqlite3
from pathlib import Path

ROOT = Path('data'); DB = ROOT / 'demo.sqlite3'; ART = ROOT / 'artifacts'
ARTIFACT_RE = re.compile(r'\b[a-zA-Z_]+-[0-9a-f]{20}\b')
FILE_RE = re.compile(r'\bfile-[0-9a-f]{20}\b')

conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True); conn.row_factory = sqlite3.Row
tasks = {r['id']: json.loads(r['state']) for r in conn.execute('SELECT id, state FROM tasks')}
events = {}
for r in conn.execute('SELECT task_id, event FROM events'):
    events.setdefault(r['task_id'], []).append(r['event'])
art_rows = {r['id'] for r in conn.execute('SELECT id FROM artifacts')}
conn.close()

L = []
def p(*a): L.append(' '.join(str(x) for x in a))

p('===== 剩余任务 =====')
for tid, s in sorted(tasks.items()):
    p('  %s kind=%s phase=%s' % (tid, s.get('kind'), s.get('phase')))

broken = []
total_refs = 0
for tid, s in sorted(tasks.items()):
    text = json.dumps(s, ensure_ascii=False) + ''.join(events.get(tid, []))
    refs = set(ARTIFACT_RE.findall(text))
    files = set(FILE_RE.findall(text))
    total_refs += len(refs)
    missing_row = [r for r in refs if r not in art_rows]
    missing_file = [r for r in refs if r in art_rows and not (ART / (r + '.json')).exists()]
    for r in sorted(set(missing_row) | set(missing_file)):
        broken.append((tid, r, 'row' if r in missing_row else 'file'))
    p('  %s: refs=%d file_refs=%d missing=%d' % (tid[:12], len(refs), len(files), len(set(missing_row)|set(missing_file))))

p('')
p('===== 校验结果 =====')
p('活跃任务 %d 个，引用工件合计 %d，断链 %d' % (len(tasks), total_refs, len(broken)))
for tid, r, why in broken:
    p('  BROKEN %s %s (%s)' % (tid, r, why))
p('RESULT: %s' % ('OK 无断链' if not broken else 'FAIL 存在断链'))

with open('data/_verify_result.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(L))
print('WROTE data/_verify_result.txt tasks=%d refs=%d broken=%d' % (len(tasks), total_refs, len(broken)))
