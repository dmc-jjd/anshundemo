"""上传文件的原始文件名索引（模板名称自动识别的唯一取名字面源）。

`/api/files` 落盘用的名字是 `file-<sha>.<ext>`，用户上传时的原始文件名随即丢失；
「新建比对任务时默认取第一份上传文件的文件名」需要它，故在 uploads 目录留一份旁路索引。
索引文件名带前导点，且 `_resolve_files` 用的是 `glob(fid+'.*')`，不会与之相撞。

读失败一律当没有：文件名只是默认值，不该让上传或建任务失败。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

INDEX_NAME = '.names.json'


def _index(uploads) -> Path:
    return Path(uploads) / INDEX_NAME


def _read(uploads) -> dict:
    try:
        data = json.loads(_index(uploads).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def remember(uploads, file_id, name) -> None:
    """记下 `file_id` 对应的原始文件名（同 id 覆盖写）。"""
    path = _index(uploads)
    data = _read(uploads)
    data[str(file_id)] = str(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def lookup(uploads, file_id, default='') -> str:
    """取 `file_id` 的原始文件名；没记过就返回 default。"""
    return str(_read(uploads).get(str(file_id)) or default)
