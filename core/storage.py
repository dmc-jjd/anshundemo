"""存储层：工件落盘 + sqlite 状态库（WP-S8-L3，自 `app/storage.py` 逐字搬迁）。

唯一的改动是**根目录的惰性化**（`docs/team/任务分解-S8.md` §3-2）：
`def __init__(self, root: Path = DATA)` 的默认值在**类定义期**求值——搬进 core 后 import 期就要
`DATA`，而基座不能读宿主 `config`。改为 `root=None` + 函数内 `data_root()`。

M2 起默认根是**当前包的包数据根**（`data/packages/<包>/`）：`Store()` 不再等于「部署唯一根」，
`Store(package='demo_b')` 或不传根时按上下文包解析；`root=` 显式给根的旧口径一字未变
（测试/脚本的 `Store(tmp_path)` 仍完全独立）。

`self.db = root/'demo.sqlite3'` 与 `self.files = root/'artifacts'` 的路径口径一字未变——
这是 G-GOLDEN 的判据，不是可选项。

`.timing` / `.event_analysis` 仍保持函数内 import（现状如此；环内不在 import 期新增边）。
"""
from __future__ import annotations
import hashlib, json, os, sqlite3, tempfile, uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from .paths import data_root
from .schemas import HumanDecision, TaskState, now

class ConflictError(Exception): pass
class Store:
    def __init__(self, root=None, package=None):
        #: 这个 Store 属于哪个客户包（`None`/'' = 调用方显式给根，如测试/脚本；不明归属）。
        #: 只用于「共享价目表放哪」这类**非产物**判定，绝不进 artifact payload。
        self.package = str(package) if package else None
        root = Path(root) if root else data_root(self.package)
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.files = self.root/'artifacts'; self.files.mkdir(exist_ok=True)
        self.db = self.root/'demo.sqlite3'
        with self.connect() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, task_id TEXT,kind TEXT,path TEXT,hash TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, state TEXT NOT NULL, revision INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT,at TEXT,event TEXT);
CREATE TABLE IF NOT EXISTS idempotency(key TEXT PRIMARY KEY, value TEXT);''')
            c.execute('CREATE TABLE IF NOT EXISTS review_drafts(task_id TEXT PRIMARY KEY,analysis_ref TEXT NOT NULL,data_ref TEXT NOT NULL,version INTEGER NOT NULL,updated_at TEXT NOT NULL)')
    def connect(self):
        c=sqlite3.connect(self.db, timeout=30); c.row_factory=sqlite3.Row; return c
    @contextmanager
    def _artifact_transaction(self):
        # All artifact writers take the same SQLite lock before touching shared hash files.
        # Cleanup runs while that lock is held, so a failed create cannot remove a rival's file.
        c=self.connect(); created=[]
        try:
            c.execute('BEGIN IMMEDIATE')
            yield c,created
            c.commit()
        except BaseException:
            try:
                for path in created:path.unlink(missing_ok=True)
            finally:
                c.rollback()
            raise
        finally:
            c.close()
    def _put_artifact(self,c,created,task_id,kind,payload,*,owner_scoped=False):
        raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,default=str).encode()
        digest=hashlib.sha256(raw).hexdigest(); aid=f'{kind}-{digest[:20]}'
        if owner_scoped:
            identity=hashlib.sha256(task_id.encode()+b'\0'+raw).hexdigest()
            aid=f'{kind}-{identity[:20]}'
        target=self.files/f'{aid}.json'
        if not target.exists():
            indexed=c.execute('SELECT 1 FROM artifacts WHERE id=?',(aid,)).fetchone()
            fd,tmp=tempfile.mkstemp(dir=self.files, suffix='.tmp')
            try:
                with os.fdopen(fd,'wb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
                os.replace(tmp,target)
                if not indexed:created.append(target)
            finally:
                if os.path.exists(tmp): os.unlink(tmp)
        c.execute('INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?,?,?)',(aid,task_id,kind,str(target),digest,now()))
        return aid
    def put_artifact(self,task_id:str,kind:str,payload:Any)->str:
        with self._artifact_transaction() as (c,created):
            return self._put_artifact(c,created,task_id,kind,payload)
    def create_report_once(self,state:TaskState,parameters:dict,idempotency_key:str|None=None)->TaskState:
        """Commit a report, parameters and its package-local idempotency claim together."""
        candidate=state.model_copy(deep=True)
        with self._artifact_transaction() as (c,created):
            if idempotency_key:
                prior=c.execute('SELECT value FROM idempotency WHERE key=?',(idempotency_key,)).fetchone()
                if prior:
                    row=c.execute('SELECT state FROM tasks WHERE id=?',(prior['value'],)).fetchone()
                    if row:return TaskState.model_validate_json(row['state'])
                    # Repair a legacy dangling claim only when no task can be returned.
                    c.execute('DELETE FROM idempotency WHERE key=?',(idempotency_key,))
                c.execute('INSERT INTO idempotency VALUES(?,?)',(idempotency_key,candidate.id))
            if parameters:
                candidate.metadata['report_parameters']=dict(parameters)
                candidate.metadata['report_parameters_ref']=self._put_artifact(c,created,candidate.id,
                    'report_parameters',{'parameters':parameters,'source':'report_processing_form'},owner_scoped=True)
            candidate.metadata['report_dispatch']='pending'
            from .timing import transition
            transition(candidate)
            c.execute('INSERT INTO tasks VALUES(?,?,?)',(candidate.id,candidate.model_dump_json(),candidate.revision))
        return candidate
    def get_artifact(self,ref:str)->Any:
        # 空引用 = 调用方手里没有产物 id（例如关掉去重/分类后 details 里没有 event_ref），
        # 不是「某个 artifact id 在库里不存在」。给带语义的 ValueError，绝不让 None 进 SQL
        # 后抛 KeyError(None)（QA2 B1：数据审核确认 500 的根因）。
        if not ref: raise ValueError('artifact_ref_missing: 该审核项引用的产物不存在（对应功能可能已关闭），请重新打开审核页')
        with self.connect() as c: row=c.execute('SELECT * FROM artifacts WHERE id=?',(ref,)).fetchone()
        if not row: raise KeyError(ref)
        path=self.files/f'{ref}.json'
        if not path.exists():path=Path(row['path'])
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['hash']: raise ValueError('artifact_hash_mismatch')
        return json.loads(raw)
    def artifact_belongs_to_task(self,ref:str,task_id:str)->bool:
        with self.connect() as c: row=c.execute('SELECT task_id FROM artifacts WHERE id=?',(ref,)).fetchone()
        return bool(row and row['task_id']==task_id)
    def put_task(self,state:TaskState,expected_revision:int|None=None,allow_resume:bool=False)->TaskState:
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT revision,state FROM tasks WHERE id=?',(state.id,)).fetchone()
            if row:
                if expected_revision is None or row['revision']!=expected_revision: raise ConflictError('stale_task_revision')
                previous=json.loads(row['state'])
                if previous.get('phase')=='paused' and not allow_resume:
                    state.phase='paused'
                    for key in ('paused_from_phase','paused_at'):
                        if key in previous.get('metadata',{}):state.metadata[key]=previous['metadata'][key]
                from .timing import transition
                transition(state,previous)
                state.revision=expected_revision+1
                updated=c.execute('UPDATE tasks SET state=?,revision=? WHERE id=? AND revision=?',(state.model_dump_json(),state.revision,state.id,expected_revision))
                if updated.rowcount!=1:raise ConflictError('stale_task_revision')
            else:
                if expected_revision not in (None,0): raise ConflictError('stale_task_revision')
                from .timing import transition
                transition(state)
                c.execute('INSERT INTO tasks VALUES(?,?,?)',(state.id,state.model_dump_json(),state.revision))
        return state
    def get_task(self,task_id:str)->TaskState:
        with self.connect() as c: row=c.execute('SELECT state FROM tasks WHERE id=?',(task_id,)).fetchone()
        if not row: raise KeyError(task_id)
        return TaskState.model_validate_json(row['state'])
    def list_tasks(self)->list[TaskState]:
        with self.connect() as c: rows=c.execute('SELECT state FROM tasks ORDER BY rowid DESC').fetchall()
        return [TaskState.model_validate_json(r['state']) for r in rows]
    def delete_task(self, task_id: str, *, keep_artifact_ids: list[str] | tuple[str, ...] = ()) -> list[str]:
        """永久删除任务及其事件、审核草稿，以及未被保留的工件（库记录与文件）。

        ``keep_artifact_ids`` 里的工件行仍挂在原 ``task_id`` 上，``get_artifact`` 仍可用。
        任务不存在时只清理能清理的行，返回已删除的 artifact id 列表，不抛错。
        """
        keep = {str(x) for x in keep_artifact_ids if x}
        deleted: list[str] = []
        with self.connect() as c:
            rows = c.execute('SELECT id, path FROM artifacts WHERE task_id=?', (task_id,)).fetchall()
            for row in rows:
                aid = row['id']
                if aid in keep:
                    continue
                c.execute('DELETE FROM artifacts WHERE id=?', (aid,))
                path = self.files / f'{aid}.json'
                if not path.exists():
                    path = Path(row['path'])
                try:
                    if path.exists():
                        path.unlink()
                except OSError:
                    pass
                deleted.append(aid)
            c.execute('DELETE FROM events WHERE task_id=?', (task_id,))
            c.execute('DELETE FROM review_drafts WHERE task_id=?', (task_id,))
            c.execute('DELETE FROM tasks WHERE id=?', (task_id,))
        return deleted
    def get_review_draft(self,task_id,analysis_ref=None):
        with self.connect() as c:row=c.execute('SELECT * FROM review_drafts WHERE task_id=?',(task_id,)).fetchone()
        if not row or analysis_ref is not None and row['analysis_ref']!=analysis_ref:return None
        return {**dict(row),'data':self.get_artifact(row['data_ref'])}
    def put_review_draft(self,task_id,analysis_ref,data,expected_version=None):
        ref=self.put_artifact(task_id,'data_review_draft',data)
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT version,analysis_ref FROM review_drafts WHERE task_id=?',(task_id,)).fetchone()
            current=row['version'] if row and row['analysis_ref']==analysis_ref else 0
            if expected_version is not None and expected_version!=current:raise ConflictError('stale_review_draft')
            version=current+1;at=now()
            c.execute('INSERT OR REPLACE INTO review_drafts VALUES(?,?,?,?,?)',(task_id,analysis_ref,ref,version,at))
        self.append_event(task_id,{'type':'data_review_draft_saved','analysis_ref':analysis_ref,'data_ref':ref,'version':version})
        return {'version':version,'updated_at':at,'data_ref':ref}
    def append_event(self,task_id:str,event:dict):
        with self.connect() as c: c.execute('INSERT INTO events(task_id,at,event) VALUES(?,?,?)',(task_id,now(),json.dumps(event,ensure_ascii=False)))
    def events(self,task_id:str,after:int=0,limit:int|None=None)->list[dict]:
        with self.connect() as c:
            if limit is None:rows=c.execute('SELECT * FROM events WHERE task_id=? AND seq>? ORDER BY seq',(task_id,after)).fetchall()
            else:rows=list(reversed(c.execute('SELECT * FROM events WHERE task_id=? AND seq>? ORDER BY seq DESC LIMIT ?',(task_id,after,max(1,min(limit,200)))).fetchall()))
        return [{'seq':r['seq'],'at':r['at'],**json.loads(r['event'])} for r in rows]
    def idempotent(self,key:str,value:str)->str:
        with self.connect() as c:
            c.execute('INSERT OR IGNORE INTO idempotency VALUES(?,?)',(key,value))
            return c.execute('SELECT value FROM idempotency WHERE key=?',(key,)).fetchone()['value']
    def apply_decision(self,task_id:str,decision:HumanDecision)->TaskState:
        state=self.get_task(task_id)
        if state.revision!=decision.expected_revision: raise ConflictError('stale_decision')
        item=next((x for x in state.review_items if x['id']==decision.item_id),None)
        if not item: raise KeyError(decision.item_id)
        if item['status']!='open': raise ConflictError('already_decided')
        if item.get('kind')=='template_exception':raise ValueError('use_template_exception_editor')
        if item.get('kind')=='writing_review':raise ValueError('use_writing_review_editor')
        if decision.action not in item.get('allowed_actions',['confirm','modify','merge','split','independent','exclude','defer']): raise ValueError('action_not_allowed_for_item')
        if item.get('kind')=='data_review' and decision.action!='defer':
            if state.fact_ref:raise ValueError('frozen_facts')
            # 模板开关关掉的段落**没有产物**，这是用户的选择而不是缺件：缺哪段就跳过哪段校验，
            # 但下面仍写出 confirmed_* 产物（允许空组），冻结/写作因此有一条可走的路。
            from .structured_template import template_feature_switches
            features=template_feature_switches(state,self)
            details=item['details']
            event_ref=details.get('event_ref');cluster_ref=details.get('cluster_ref')
            events=self.get_artifact(event_ref) if event_ref else None
            themes=self.get_artifact(cluster_ref) if cluster_ref else None
            if features['dedup'] and events is None:raise ValueError('event_analysis_missing: 事件归并产物不存在，请按新规则重新处理')
            if features['classification'] and themes is None:raise ValueError('event_clusters_missing: 自动分类产物不存在，请按新规则重新处理')
            groups=(decision.payload.get('groups',(events or {}).get('groups',[]))) or []
            theme_fallback=(events or {}).get('theme_groups') or (themes or {}).get('groups') or []
            theme_groups=(decision.payload.get('themes',theme_fallback)) or []
            if events is not None:
                if 'analysis_ref' not in details:raise ValueError('event_analysis_required')
                if events.get('pending_model'):raise ValueError('model_analysis_pending')
                expected=set(events['all_record_ids'])
                group_ids=[g.get('id') for g in groups]
                if any(not key for key in group_ids) or len(group_ids)!=len(set(group_ids)) or any(g.get('representative_id') not in g['member_ids'] for g in groups):
                    raise ValueError('invalid_event_group_identity')
                # 分类开关关掉（或分类产物缺失）时没有可对照的主题分组：只校验事件成员覆盖。
                for collection in ((groups,theme_groups) if themes is not None else (groups,)):
                    if not isinstance(collection,list) or not collection:raise ValueError('review_groups_required')
                    ids=[rid for group in collection for rid in group.get('member_ids',[])]
                    if len(ids)!=len(set(ids)) or set(ids)!=expected:raise ValueError('review_members_must_cover_records_once')
                if themes is not None:
                    if any(not group.get('candidate_theme','').strip() for group in theme_groups):raise ValueError('theme_name_required')
                    if any(group['candidate_theme'] in ('待人工分类','模型尚未处理') and group['member_ids'] for group in theme_groups):raise ValueError('uncertain_classification_unresolved')
                    categories={rid:g['candidate_theme'] for g in theme_groups for rid in g['member_ids']}
                    if any(len({categories[rid] for rid in g['member_ids']})!=1 for g in groups):raise ValueError('event_category_must_be_consistent')
                assignments={rid:index for index,g in enumerate(groups) for rid in g['member_ids']}
                merge_decisions=decision.payload.get('merge_decisions',{})
                for case in events.get('merge_ambiguities',[]):
                    action=merge_decisions.get(case['id'])
                    if action not in ('same','different'):raise ValueError('merge_ambiguity_unresolved')
                    together=assignments[case['source_id']]==assignments[case['target_id']]
                    if together!=(action=='same'):raise ValueError('merge_decision_members_disagree')
            if features['top10'] and events is not None:
                from .event_analysis import negative_ranking
                source=self.get_artifact(state.result_refs['filter_records:negative_or_warning'])['records']
                ranked=negative_ranking(groups,source)
                available={row['fingerprint']:row for row in events.get('top10',[])}
                patches=decision.payload.get('briefs',{})
                top10=[]
                for rank,row in enumerate(ranked,1):
                    brief=patches.get(row['fingerprint'],available.get(row['fingerprint']))
                    if not brief:raise ValueError('top10_needs_refresh')
                    if brief.get('status')!='complete' or not str(brief.get('summary','')).strip():raise ValueError('top10_summary_required')
                    if not 15<=len(brief['summary'].strip())<=35:raise ValueError('top10_summary_length')
                    if not brief.get('source_refs') or not set(brief['source_refs'])<=set(row['negative_ids']):raise ValueError('invalid_top10_sources')
                    top10.append({**row,'rank':rank,'summary':brief['summary'],'source_refs':brief['source_refs'],'status':'complete'})
                state.metadata['reviewed_top10']=top10
            else:
                # 模板关掉 TOP10，或没有事件（去重关）：该段不产出，也就没有梗概可校验。
                # 其余数据审核校验（组成员覆盖、分类一致、关系裁决）照旧逐条执行。
                state.metadata['reviewed_top10']=[]
            state.result_refs['confirmed_event_groups']=self.put_artifact(task_id,'confirmed_event_groups',{'groups':groups,'source_ref':event_ref,'decision':decision.model_dump()})
            state.result_refs['confirmed_theme_groups']=self.put_artifact(task_id,'confirmed_theme_groups',{'groups':theme_groups,'source_ref':cluster_ref,'decision':decision.model_dump()})
        if item.get('kind')=='event_scope' and decision.action!='defer':
            scope=decision.payload.get('scope')
            if scope not in ('all','negative','warning','negative_warning','negative_or_warning'): raise ValueError('event_scope_choice_required')
            state.metadata['event_scope']=scope
            state.metadata['event_scope_confirmed']=True
        if item.get('kind')=='event_groups' and decision.action!='defer':
            if decision.action=='confirm' and decision.payload.get('strategy')=='accept_keyword_groups':
                prior=self.get_artifact(item['details']['keyword_ref'])
                groups=[{'member_ids':g['member_ids']} for g in prior['groups']]
            else:
                groups=decision.payload.get('groups')
                if not isinstance(groups,list): raise ValueError('event_groups_payload_required')
            prior=self.get_artifact(item['details']['keyword_ref'])
            expected=set(prior['all_record_ids']); members=[rid for g in groups for rid in g.get('member_ids',[])]
            excluded=set(decision.payload.get('excluded_ids',[]))
            if len(members)!=len(set(members)) or set(members)&excluded or set(members)|excluded!=expected:
                raise ValueError('event_group_members_must_cover_all_source_records_once')
            event_ref=self.put_artifact(task_id,'confirmed_event_groups',{'groups':groups,'excluded_ids':sorted(excluded),'keyword_ref':item['details']['keyword_ref'],'vector_ref':item['details']['vector_ref'],'decision':decision.model_dump()})
            state.result_refs['confirmed_event_groups']=event_ref
        if item.get('kind')=='theme_clusters' and decision.action!='defer':
            prior=self.get_artifact(item['details']['cluster_ref'])
            groups=prior['groups'] if decision.action=='confirm' else decision.payload.get('groups')
            if not isinstance(groups,list): raise ValueError('theme_groups_payload_required')
            ids=[rid for group in groups for rid in group.get('member_ids',[])]
            if len(ids)!=len(set(ids)) or set(ids)!=set(prior['all_record_ids']): raise ValueError('theme_group_members_must_cover_all_source_records_once')
            theme_ref=self.put_artifact(task_id,'confirmed_theme_groups',{'groups':groups,'source_cluster_ref':item['details']['cluster_ref'],'decision':decision.model_dump()})
            state.result_refs['confirmed_theme_groups']=theme_ref
        if item.get('kind')=='template_business_question' and decision.action!='defer':
            if not str(decision.payload.get('answer','')).strip():raise ValueError('template_question_answer_required')
        item['status']='deferred' if decision.action=='defer' else 'resolved'
        item['decision']=decision.model_dump()
        self.put_task(state,decision.expected_revision)
        self.append_event(task_id,{'type':'human_decision','item_id':item['id'],'action':decision.action,'reason':decision.reason})
        return state

