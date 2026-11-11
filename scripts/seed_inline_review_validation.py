"""Create a separate UI fixture; production facts and human decisions stay intact."""
import re,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.storage import Store

root=ROOT/'data/inline-review-ui-20261108';root.mkdir(exist_ok=True)
with sqlite3.connect(ROOT/'data/demo.sqlite3') as source,sqlite3.connect(root/'demo.sqlite3') as target:source.backup(target)
store=Store(root);tid='d2511637eb694125a92616d2a276bd08';state=store.get_task(tid)
draft=store.get_artifact(state.draft_ref);paragraph=draft['slot_values']['monthly_recommendations']['value'][1]
sentences=re.findall(r'[^。！？]+[。！？]',paragraph);assert len(sentences)>=2 and sentences[0]!=sentences[1]
for issue in state.review_items:
    if issue['kind']=='writing_review':issue.update(status='superseded',blocking=False)
for key,field,quote in [('retain','b26_focus_reports',draft['slot_values']['b26_focus_reports']['value'][:25]),('inline-a','monthly_recommendations',sentences[0]),('inline-b','monthly_recommendations',sentences[1])]:
    state.review_items.append({'id':key,'kind':'writing_review','reviewer':'content_reviewer','status':'open','blocking':True,'draft_hash':draft['content_hash'],
        'question':'模拟逐条人审','details':{'field_id':field,'quote':quote,'description':'模拟：核对后可保留或直接修改这处原文。','suggestion':'仅替换所选原句，保留其他段落。','action':'revise'},'allowed_actions':['confirm']})
state.metadata['writing_review_run']['review_item_order']=['retain','inline-a','inline-b'];state.metadata['simulation']=True
state.phase='awaiting_final_review';store.put_task(state,state.revision)
print(root)
