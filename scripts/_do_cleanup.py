"""执行清理：删除 23 个暂停任务及其独占工件。先备份 DB，只删孤儿工件，不触碰共享工件。"""
import json, re, sqlite3, shutil
from pathlib import Path
from datetime import datetime

ROOT = Path('data')
DB = ROOT / 'demo.sqlite3'
ART_DIR = ROOT / 'artifacts'
ARTIFACT_RE = re.compile(r'\b[a-zA-Z_]+-[0-9a-f]{20}\b')

# 1. 备份 DB
bak = ROOT / ('demo.sqlite3.bak-%s' % datetime.now().strftime('%Y%m%d-%H%M%S'))
shutil.copy2(DB, bak)

conn = sqlite3.connect(DB, timeout=30)
conn.row_factory = sqlite3.Row

tasks = {r['id']: json.loads(r['state']) for r in conn.execute('SELECT id, state FROM tasks')}
events = {}
for r in conn.execute('SELECT task_id, event FROM events'):
    events.setdefault(r['task_id'], []).append(r['event'])

paused_ids = {tid for tid, s in tasks.items() if s.get('phase') == 'paused'}
active_ids = set(tasks) - paused_ids

def refs_state(s):
    return set(ARTIFACT_RE.findall(json.dumps(s, ensure_ascii=False)))
def refs_events(tid):
    return set(ARTIFACT_RE.findall(''.join(events.get(tid, []))))

paused_artifacts = set()
for tid in paused_ids:
    paused_artifacts |= refs_state(tasks[tid]) | refs_events(tid)
active_artifacts = set()
for tid in active_ids:
    active_artifacts |= refs_state(tasks[tid]) | refs_events(tid)

orphan = paused_artifacts - active_artifacts
shared = paused_artifacts & active_artifacts

# 2. 删除 DB 行
with conn:
    cur = conn.cursor()
    n_tasks = n_events = n_rd = n_idem = n_art = 0
    for tid in paused_ids:
        cur.execute('DELETE FROM tasks WHERE id=?', (tid,)); n_tasks += cur.rowcount
        cur.execute('DELETE FROM events WHERE task_id=?', (tid,)); n_events += cur.rowcount
        cur.execute('DELETE FROM review_drafts WHERE task_id=?', (tid,)); n_rd += cur.rowcount
        cur.execute('DELETE FROM idempotency WHERE value=?', (tid,)); n_idem += cur.rowcount
    for a in orphan:
        cur.execute('DELETE FROM artifacts WHERE id=?', (a,)); n_art += cur.rowcount

# 3. 删除独占工件文件
deleted_files = 0
manifest = []
for a in sorted(orphan):
    f = ART_DIR / (a + '.json')
    if f.exists():
        f.unlink()
        deleted_files += 1
        manifest.append(a)

# 4. 校验
remaining = [r['id'] for r in conn.execute('SELECT id FROM tasks')]
remaining_paused = [tid for tid in remaining if json.loads(conn.execute('SELECT state FROM tasks WHERE id=?', (tid,)).fetchone()['state']).get('phase') == 'paused']
conn.close()

# 写删除清单
with open('data/_cleanup_manifest.txt', 'w', encoding='utf-8') as f:
    f.write('backup=%s\n' % bak)
    f.write('paused_ids_deleted=%d\n' % len(paused_ids))
    f.write('\n'.join(sorted(paused_ids)))
    f.write('\n\n# orphan artifact files deleted (%d)\n' % deleted_files)
    f.write('\n'.join(manifest))

print('BACKUP=%s' % bak)
print('deleted tasks=%d events=%d review_drafts=%d idempotency=%d artifact_rows=%d files=%d' % (
    n_tasks, n_events, n_rd, n_idem, n_art, deleted_files))
print('orphan=%d shared_kept=%d remaining_tasks=%d remaining_paused=%d' % (
    len(orphan), len(shared), len(remaining), len(remaining_paused)))
