"""只读分析：暂停任务及其独占工件/上传文件，输出删除范围。不改任何数据。"""
import json, re, sqlite3
from pathlib import Path

ROOT = Path('data')
DB = ROOT / 'demo.sqlite3'

ARTIFACT_RE = re.compile(r'\b[a-zA-Z_]+-[0-9a-f]{20}\b')
FILE_RE = re.compile(r'\bfile-[0-9a-f]{20}\b')

conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
conn.row_factory = sqlite3.Row

tasks = {r['id']: json.loads(r['state']) for r in conn.execute('SELECT id, state FROM tasks')}
events = {}
for r in conn.execute('SELECT task_id, event FROM events'):
    events.setdefault(r['task_id'], []).append(r['event'])

paused_ids = {tid for tid, s in tasks.items() if s.get('phase') == 'paused'}
active_ids = set(tasks) - paused_ids

def refs_of_state(s):
    """从任务 state JSON 提取所有工件 ref 与 file ref。"""
    text = json.dumps(s, ensure_ascii=False)
    return set(ARTIFACT_RE.findall(text)), set(FILE_RE.findall(text))

def refs_of_events(tid):
    a, f = set(), set()
    for ev in events.get(tid, []):
        a |= set(ARTIFACT_RE.findall(ev))
        f |= set(FILE_RE.findall(ev))
    return a, f

def refs_of(tid):
    a, f = refs_of_state(tasks[tid])
    ea, ef = refs_of_events(tid)
    return a | ea, f | ef

paused_artifacts, paused_files = set(), set()
for tid in paused_ids:
    a, f = refs_of(tid)
    paused_artifacts |= a
    paused_files |= f

active_artifacts, active_files = set(), set()
for tid in active_ids:
    a, f = refs_of(tid)
    active_artifacts |= a
    active_files |= f

# 共享工件：暂停任务引用、但也被非暂停任务引用 —— 不能删
shared_artifacts = paused_artifacts & active_artifacts
shared_files = paused_files & active_files
orphan_artifacts = paused_artifacts - active_artifacts
orphan_files = paused_files - active_files

# 工件表：仅记录首个创建者的 task_id，据此也能推断「哪些工件文件实际存在」
artifact_rows = {r['id']: r['task_id'] for r in conn.execute('SELECT id, task_id FROM artifacts')}
orphan_on_disk = {a for a in orphan_artifacts if a in artifact_rows}
orphan_missing_row = orphan_artifacts - set(artifact_rows)  # 被引用但无表记录（理论不该发生）

# 上传文件磁盘上的实际存在情况
uploads = set(p.name for p in (ROOT / 'uploads').glob('*')) if (ROOT / 'uploads').exists() else set()

L = []
def p(*a): L.append(' '.join(str(x) for x in a))

p('===== 任务统计 =====')
p('总任务 %d；暂停 %d；非暂停(活跃) %d' % (len(tasks), len(paused_ids), len(active_ids)))

p('')
p('===== 暂停任务清单 (%d) =====' % len(paused_ids))
for tid in sorted(paused_ids, key=lambda t: tasks[t]['id']):
    s = tasks[tid]
    p('  %s kind=%s phase=%s created=%s' % (tid, s.get('kind'), s.get('phase'), s.get('created_at')))

p('')
p('===== 活跃任务清单 (%d) —— 保留，不删 =====' % len(active_ids))
for tid in sorted(active_ids, key=lambda t: tasks[t]['id']):
    s = tasks[tid]
    p('  %s kind=%s phase=%s' % (tid, s.get('kind'), s.get('phase')))

p('')
p('===== 工件引用分析 =====')
p('暂停任务引用的工件 ref 总数：%d' % len(paused_artifacts))
p('活跃任务引用的工件 ref 总数：%d' % len(active_artifacts))
p('  共享(暂停∩活跃，不能删)：%d' % len(shared_artifacts))
for a in sorted(shared_artifacts):
    owners = sorted({tid for tid, s in tasks.items() if a in refs_of_state(s)[0]})
    p('    SHARED %s  <- 活跃任务 %s' % (a, [t for t in owners if t in active_ids]))
p('  独占(仅暂停引用，可删)：%d' % len(orphan_artifacts))
p('    其中工件表有记录(磁盘有文件)：%d' % len(orphan_on_disk))
p('    其中工件表无记录(异常)：%d' % len(orphan_missing_row))

p('')
p('===== 上传文件引用分析 =====')
p('暂停任务引用的 file ref 总数：%d' % len(paused_files))
p('活跃任务引用的 file ref 总数：%d' % len(active_files))
p('  共享(不能删)：%d %s' % (len(shared_files), sorted(shared_files)))
p('  独占(可删)：%d %s' % (len(orphan_files), sorted(orphan_files)))

p('')
p('===== 数据库各表待删行数(暂停任务) =====')
p('tasks 行：%d' % len(paused_ids))
p('events 行：%d' % sum(len(events.get(t, [])) for t in paused_ids))
rd = [r['task_id'] for r in conn.execute('SELECT task_id FROM review_drafts')]
p('review_drafts 行：%d' % sum(1 for t in paused_ids if t in rd))
idem = [r['value'] for r in conn.execute('SELECT value FROM idempotency')]
p('idempotency 行：%d' % sum(1 for t in paused_ids if t in idem))

p('')
p('===== 磁盘文件规模 =====')
art_dir = ROOT / 'artifacts'
p('artifacts 目录现有 .json 文件：%d' % (len(list(art_dir.glob('*.json'))) if art_dir.exists() else 0))
p('uploads 目录现有文件：%d' % len(uploads))

with open('data/_cleanup_plan.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(L))
print('WROTE data/_cleanup_plan.txt  lines=%d paused=%d orphan_artifacts=%d orphan_files=%d shared_artifacts=%d' % (
    len(L), len(paused_ids), len(orphan_artifacts), len(orphan_files), len(shared_artifacts)))
