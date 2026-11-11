"""WP-S7-C：把「任意客户包都能被基座加载」变成对**所有包**生效的判据（3 个用例）。

为什么这三个用例必须遍历 `packages/*/` 而不是只测 demo_b：
    B 一个包通过只证明「B 恰好能装进来」；下一个客户包仍可能踩同一个坑。
    遍历面来自目录本身（不是一张手写清单），所以新增包自动进判据——这也是 §6 D7
    「B 进 `packages/` 而不是 `tests/fixtures/`」的理由。

与 `tests/test_s5_*` 的分工：S5 的用例钉的是 **A 一个包**的键序/字节/结构；
本文件钉的是 **任意包** 都必须满足的三条最小契约（能加载 / 提示词提到的技能已声明 / 提示词字节口径）。

三条都不许在进程内 `configure`（四个注册表是 module-global，`§5 RISK-1`），所以第 1 条走子进程。
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.manifest import load_manifest  # noqa: E402

PACKAGES = sorted(path for path in (REPO / 'packages').iterdir()
                  if path.is_dir() and (path / 'manifest.yaml').is_file())

#: 子进程里跑 `import app`——`app/__init__.py:8-12` 就是那四件 configure 的唯一组合根。
#: 打印计数是为了让 FAIL 时能看出「加载到了什么」，而不是只知道非零退出。
LOAD_SCRIPT = (
    "import app\n"
    "from app.config import PACKAGE\n"
    "from core.charts import registry as charts\n"
    "from core.prompts import registry as prompts\n"
    "from core.skills import registry as skills\n"
    "from core.tools import vocabulary\n"
    "print('PKG-OK', PACKAGE, len(charts.ids()), len(prompts.prompts()),"
    " len(prompts.roles()), len(vocabulary.localities()), skills.style_skill())\n"
)


def _registered_skill_ids() -> set[str]:
    """已注册技能 id = `core/skills/<pack>/*.json` 的描述符名 ∪ `skills/` 下的资产目录名。

    只有描述符名与资产目录名算"已注册"：`source-binding` 这类纯代码技能（无描述符、无资产目录）
    不在集合里——任务分解 F8 实测提示词里另一个 kebab token `per-event` 是普通英文，不是技能。
    """
    ids = {path.stem for path in (REPO / 'core' / 'skills').glob('*/*.json')}
    ids |= {path.name for path in (REPO / 'skills').iterdir() if path.is_dir()}
    assert ids, '注册技能集合为空会让债 6 的用例空转通过'
    return ids


def test_every_package_loads_in_isolated_process() -> None:
    assert PACKAGES, '扫描面为空会让本用例空转通过'
    for package in PACKAGES:
        env = {**os.environ, 'REPORT_PACKAGE': package.name, 'PYTHONIOENCODING': 'utf-8'}
        done = subprocess.run([sys.executable, '-c', LOAD_SCRIPT], cwd=str(REPO), env=env,
                              capture_output=True, text=True, encoding='utf-8', timeout=300)
        assert done.returncode == 0, f'{package.name} 加载失败\n{done.stdout}\n{done.stderr}'
        assert f'PKG-OK {package.name} ' in done.stdout, f'{package.name} 的计数行缺失: {done.stdout!r}'


def test_prompt_skill_refs_are_declared() -> None:
    """§7 债 6 的治理测试：提示词里提到的每个**已注册技能 id** 都必须在该包的 `manifest.skills.use` 里。

    放大到 `packages/**/prompts`（S4/S5/S6 的同一笔债），且只认已注册 id——按任意 kebab 串扫会
    把 `per-event` 这类普通英文误判成技能名（F8）。
    """
    registered = _registered_skill_ids()
    hits_total = 0
    for package in PACKAGES:
        declared = set(load_manifest(package).skill_use)
        mentioned: set[str] = set()
        for path in sorted((package / 'prompts' / 'agent').glob('*.md')):
            text = path.read_text(encoding='utf-8')
            mentioned |= {skill_id for skill_id in registered if skill_id in text}
        hits_total += len(mentioned)
        assert mentioned <= declared, f'{package.name} 提到了未声明的技能: {sorted(mentioned - declared)}'
    # 非空性：A 的提示词确实写了 `lieflat-less-ai-tone`（F8 实测），扫不到就说明扫描面失效了。
    assert hits_total > 0


def test_prompt_files_end_with_at_most_one_lf() -> None:
    """提示词文件的字节口径：正文 + **至多一个**结尾 LF，加载期剥掉一个（`core/prompts/registry.py:15-17`）。

    注意方向：任务分解 §3 WP-C 写的是「每个 .md 不以换行结尾」，与实测**相反**——A 的 32 个文件
    全部以恰好一个 LF 结尾（`b'...\\n'`），剥掉那份 LF 的正是 `_bundle`。所以钉的是
    「剥一个之后不再以 LF 结尾」，它同时排除「两个及以上结尾 LF」这种会让剥一规则产生歧义的形态。
    """
    files = sorted(path for package in PACKAGES
                   for path in (package / 'prompts' / 'agent').glob('*.md'))
    assert files, '扫描面为空会让本用例空转通过'
    for path in files:
        text = path.read_bytes().decode('utf-8')
        body = text[:-1] if text.endswith('\n') else text
        assert not body.endswith('\n'), f'{path.relative_to(REPO)} 以多个换行结尾'
        assert body.strip(), f'{path.relative_to(REPO)} 去掉结尾换行后为空'
        assert re.fullmatch(r'[a-z0-9_.-]+', path.stem), path.name
