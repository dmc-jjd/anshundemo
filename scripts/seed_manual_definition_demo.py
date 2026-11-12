"""为「手动定义字段」造一个可演示的模板任务（隔离数据目录，不碰现场 data/）。

用法：
    python scripts/seed_manual_definition_demo.py --data-dir <dir> --docx a.docx b.docx
    REPORT_DEMO_DATA=<dir> python -m uvicorn app.main:app --port 8766

输出：任务 id + 前几个可编辑段落的标准文本（选区要用这段文字原文）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.schemas import TaskState  # noqa: E402
from app.storage import Store  # noqa: E402
from app.structured_template import build_structured_template  # noqa: E402
from app.template_compare import parse_report_document  # noqa: E402
from app.template_draft import block_text  # noqa: E402

TASK_ID = 'manual-definition-demo'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--docx', nargs='+', required=True)
    parser.add_argument('--limit', type=int, default=8)
    args = parser.parse_args()

    documents = [parse_report_document(path) for path in args.docx]
    definition = build_structured_template(documents, 'demo-comparison')
    store = Store(Path(args.data_dir))
    ref = store.put_artifact(TASK_ID, 'structured_template_candidate', definition)
    state = TaskState(id=TASK_ID, kind='template', phase='awaiting_template_confirmation')
    state.metadata['structured_template_ref'] = ref
    state.metadata['simulation'] = True
    try:
        store.put_task(state)
    except Exception:  # 已存在则只更新 metadata
        current = store.get_task(TASK_ID)
        current.metadata['structured_template_ref'] = ref
        store.put_task(current, current.revision)

    blocks = [{'index': b['index'], 'kind': b.get('kind'),
               'text': (block_text(b) or '')[:160]} for b in definition['blocks']]
    printable = [b for b in blocks if b['text']][:args.limit]
    print(json.dumps({'task_id': TASK_ID, 'template_ref': ref,
                      'block_count': len(blocks), 'fields': len(definition['fields']),
                      'paragraph_samples': printable}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
