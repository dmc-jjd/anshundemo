"""M1 验收核心：同进程 A/B 交叉断言（唯一能抓住「静默串包」的测试）。

为什么必须是「同进程 A/B 交叉」而不是「B 能跑通」：
    M1 之前的实现把包身份烧进进程——四个注册表 + 7 处模块级快照都在**首次 import 期**求值。
    任何一处漏改，B 任务会「顺利跑完」但产物是 A 的列名/区县/图表/提示词，**不报错**；
    而现有 300+ 用例 100% 跑默认 A 包，改动前后全绿。
    所以这里的每条断言都必须是「A 是 A 的、B 是 B 的、且 A≠B」，并**交叉调用**（A→B→A）
    后重取 A，逐字节比对——只有这样才能证明「解析没有落到某个进程级单例上」。

覆盖 7 条（编号对应任务书）：
    1 提示词：两包不同；交叉 10 次后 A 的返回值逐字节不变
    2 词表：localities / cluster_terms 各自正确，交叉后不污染
    3 列映射：COLUMN_MAP 两包不同
    4 图表清单：charts() 两包不同
    5 技能 style_id：**零参数 `@lru_cache` 那个 bug**（真实两包同 pack 同 style id，故另造
      两个 pack 不同的临时包证明键里带包；真实包另证 use() 不同）
    6 ContextVar 隔离：8 线程交替设 A/B，每个线程读到的都是自己设的包
    7 依赖零污染：`core/**` 对 `app` 的 Import 站点仍为 0
另加两条机械判据（任务书/RESEARCH 都点了名）：
    8 解析不依赖 configure()：裸 core 子进程（不 import 宿主）也能按包名解析
    9 LRU 容量 8 + 指纹进键：改文件后同一包返回新的加载结果
"""

from __future__ import annotations

import concurrent.futures
import json
import pathlib
import subprocess
import sys
import threading

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'scripts'))

import gate_core_iso  # noqa: E402

import app  # noqa: F401  （宿主在 import 期配置四个注册表；本文件只断言「解析」不看它）
from core import packages  # noqa: E402
from core.agent import get_prompt  # noqa: E402
from core.charts import registry as chart_registry  # noqa: E402
from core.packages import context as package_context_mod  # noqa: E402
from core.packages import registry as package_registry  # noqa: E402
from core.prompts import registry as prompt_registry  # noqa: E402
from core.skills import registry as skill_registry  # noqa: E402
from core.tools import vocabulary  # noqa: E402

A = 'anshun_monthly'
B = 'demo_b'

#: A 包的八区县（用于「B 的词典里一个都不该有」）。
A_LOCALITIES = ['西秀区', '平坝区', '普定县', '镇宁自治县', '关岭自治县',
                '紫云自治县', '黄果树旅游区', '安顺经开区']
B_LOCALITIES = ['景区片区', '中心城区']


# --------------------------------------------------------------------------- #
# 1 提示词
# --------------------------------------------------------------------------- #


def test_prompt_text_is_per_package_and_stable_across_interleaving():
    a_first = get_prompt('writer.analysis', package=A)
    b_first = get_prompt('writer.analysis', package=B)
    assert a_first != b_first, '两包的同一提示词键返回了同一份文本（= 读到进程级快照）'
    assert '演示包B' in b_first and '演示包B' not in a_first
    seen = [a_first]
    for _ in range(10):                      # A→B 交替 10 轮，每轮重取 A
        assert get_prompt('writer.analysis', package=B) == b_first
        seen.append(get_prompt('writer.analysis', package=A))
    assert len(set(seen)) == 1, f'A 的返回值被 B 污染了：{len(set(seen))} 种'
    assert seen[0].encode('utf-8') == a_first.encode('utf-8'), '逐字节比对失败'


def test_default_profile_and_prompt_count_follow_the_package():
    assert prompt_registry.default_profile(package=A) == A
    assert prompt_registry.default_profile(package=B) == B
    assert len(prompt_registry.prompts(package=A)) == 34
    assert len(prompt_registry.prompts(package=B)) == 10
    # 交叉后重取，键集与键序都必须还是各自包的
    assert len(prompt_registry.prompts(package=A)) == 34
    assert list(prompt_registry.prompts(package=B))[0] == 'historical_researcher.plan'


# --------------------------------------------------------------------------- #
# 2 词表
# --------------------------------------------------------------------------- #


def test_vocabulary_is_per_package_and_not_polluted():
    a_loc = vocabulary.localities(package=A)
    b_loc = vocabulary.localities(package=B)
    assert list(a_loc) == A_LOCALITIES
    assert list(b_loc) == B_LOCALITIES
    assert not (set(a_loc) & set(b_loc)), '两包的区县表出现了交集（= 串包）'

    a_terms = vocabulary.cluster_terms(package=A)
    b_terms = vocabulary.cluster_terms(package=B)
    assert len(a_terms) == 12 and len(b_terms) == 2
    assert set(b_terms) == {'景区服务', '公共服务'}

    for _ in range(5):                        # 交叉污染探测
        assert vocabulary.localities(package=B) == b_loc
        assert vocabulary.cluster_terms(package=A) == a_terms
    assert vocabulary.localities(package=A) == a_loc
    assert vocabulary.cluster_terms(package=B) == b_terms


# --------------------------------------------------------------------------- #
# 2.5 分词器：默认包零影响 + 非默认包最长匹配覆盖层
# --------------------------------------------------------------------------- #


def test_tokenizer_overlay_is_zero_impact_for_default_and_longest_match_for_others():
    """M1 的 jieba 权衡：默认包 `add_word`（与改造前逐字节一致）、其余包走最长匹配覆盖层。

    - A：覆盖层为空 → `tokenize(text, package=A)` 必须与不传包逐字节相同（热路径零开销）；
    - B：B 的词必须是**整 token**，且不许把相邻词越界拼成一个不存在的长串。
    """
    from core import text as core_text

    assert core_text._overlay(A) == ()
    sample = '安顺市平坝区社区卫生服务中心获评景区片区示范点，游客投诉明显下降'
    assert core_text.tokenize(sample) == core_text.tokenize(sample, package=A)
    b_tokens = core_text.tokenize(sample, package=B)
    assert '景区片区' in b_tokens, b_tokens
    assert '景区片区示范点' not in b_tokens, f'越界拼接：{b_tokens}'
    assert b_tokens == core_text.tokenize(sample, package=B), '覆盖层不确定'
    # 覆盖层只合并、不拆分：B 的 token 数不会多于同文本在 A 下的 token 数
    assert len(b_tokens) <= len(core_text.tokenize(sample, package=A))


# --------------------------------------------------------------------------- #
# 3 列映射（两包不同的第二份快照：core/tools/records.py）
# --------------------------------------------------------------------------- #


def test_column_map_differs_and_record_fields_follow_it():
    a_map = vocabulary.column_map(package=A)
    b_map = vocabulary.column_map(package=B)
    assert a_map != b_map
    assert '作者' in a_map and '作者' not in b_map
    assert list(a_map)[:3] == ['标题', '发布时间', '来源信息']

    from core.tool import COLUMN_MAP as shell_map

    assert shell_map == a_map, 'core/tool.py 的旧名必须仍解析默认包（A）'
    # 旧名的惰性代理与函数式 API 必须同源：改包后仍各自正确
    from core.tools import records

    assert records._data_fields(B)[1] == b_map       # 第二份快照已下沉进函数
    assert records._data_fields(B)[0] == ['标题', '舆情调性']


# --------------------------------------------------------------------------- #
# 4 图表清单
# --------------------------------------------------------------------------- #


def test_chart_lists_are_per_package():
    assert chart_registry.ids(package=A) == ['sentiment', 'daily', 'platform', 'theme', 'locality']
    assert chart_registry.ids(package=B) == ['sentiment', 'daily', 'platform']
    assert [c['final_title'] for c in chart_registry.charts(package=B)][0].endswith('（演示包B）')
    for _ in range(5):
        assert chart_registry.ids(package=B) == ['sentiment', 'daily', 'platform']
        assert len(chart_registry.charts(package=A)) == 5
    # 未知图表在 B 下也必须报错（theme 只存在于 A）
    with pytest.raises(KeyError):
        chart_registry.chart('theme', package=B)


# --------------------------------------------------------------------------- #
# 5 技能 style_id
# --------------------------------------------------------------------------- #


def test_skill_use_differs_for_real_packages():
    assert skill_registry.use(package=A) == ('lieflat-less-ai-tone', 'source-binding')
    assert skill_registry.use(package=B) == ('lieflat-less-ai-tone',)
    assert skill_registry.resolvable(package=A) == ['lieflat-less-ai-tone']
    # 真实两包共用同一个 style 技能（同 pack、同 id），所以「值不同」只能用临时 pack 证明；
    # 这里先钉住「值相同也要各自解析」的事实，见下一个用例证明缓存键里带了包。
    assert skill_registry.style_skill(package=A) == skill_registry.style_skill(package=B)


def _write_json(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(payload, ensure_ascii=False).encode('utf-8'))


def _make_package(root: pathlib.Path, name: str, pack: str, style_id: str = 'style-only') -> None:
    """最小临时包：manifest + 空 template（只有 skills.pack/use 参与本用例）。"""
    directory = root / name
    directory.mkdir(parents=True)
    (directory / 'manifest.yaml').write_bytes(
        f'package: {name}\nreport_type: 隔离用例\nversion: 0.0.0\n'
        f'template: template.json\nprompts: prompts/\n'
        f'skills:\n  pack: {pack}\n  use: [{style_id}]\n'.encode('utf-8'))
    _write_json(directory / 'template.json', {'vocabulary': {}})


def _make_skill_pack(skills_root: pathlib.Path, pack: str, style_id: str, labels: dict) -> None:
    _write_json(skills_root / pack / f'{style_id}.json',
                {'kind': 'style', 'labels': labels, 'assets': {}})


def test_style_id_is_keyed_by_package(tmp_path, monkeypatch):
    """零参数 `@lru_cache _style_id()` 的回归：两个包各自的 style 技能必须都能解析出来。

    真实两包同 pack（skill-core）且都只声明同一个 style 技能，值相同 → 用假值看不出 bug。
    这里造两个**不同 pack** 的临时包：旧实现下 `_style_id()` 零参数，第一个包的答案永久生效，
    第二包会拿到第一包的 style id（甚至 KeyError），本用例就会红。
    """
    skills_root = tmp_path / 'skills'
    assert skill_registry.style_skill() == 'lieflat-less-ai-tone'   # 先钉默认包（真实 A）再打桩
    _make_skill_pack(skills_root, 'pack-a', 'style-a', {'alpha': ['a1']})
    _make_skill_pack(skills_root, 'pack-b', 'style-b', {'beta': ['b1']})
    packages_root = tmp_path / 'packages'
    _make_package(packages_root, 'pkg_a', 'pack-a', 'style-a')
    _make_package(packages_root, 'pkg_b', 'pack-b', 'style-b')

    monkeypatch.setenv('REPORT_PACKAGES_ROOT', str(packages_root))
    monkeypatch.setattr(skill_registry, 'SKILLS_DIR', skills_root)

    assert skill_registry.style_skill(package='pkg_a') == 'style-a'
    assert skill_registry.style_skill(package='pkg_b') == 'style-b'
    assert skill_registry.labels(package='pkg_a') == {'alpha': ['a1']}
    assert skill_registry.labels(package='pkg_b') == {'beta': ['b1']}
    for _ in range(5):                       # 交替重取，缓存不得串
        assert skill_registry.style_skill(package='pkg_b') == 'style-b'
        assert skill_registry.style_skill(package='pkg_a') == 'style-a'


# --------------------------------------------------------------------------- #
# 6 ContextVar 隔离（8 线程交替 A/B）
# --------------------------------------------------------------------------- #


def _read_current_package_data() -> dict:
    """不带 `package=` 读一遍「当前包」的全部可见面（故意全走无参路径）。"""
    return {
        'default_profile': prompt_registry.default_profile(),
        'prompt': get_prompt('writer.analysis'),
        'localities': tuple(vocabulary.localities()),
        'charts': tuple(chart_registry.ids()),
        'style': skill_registry.style_skill(),
        'current': packages.current_package(),
    }


def _expected(package: str) -> dict:
    return {
        'default_profile': prompt_registry.default_profile(package=package),
        'prompt': get_prompt('writer.analysis', package=package),
        'localities': tuple(vocabulary.localities(package=package)),
        'charts': tuple(chart_registry.ids(package=package)),
        'style': skill_registry.style_skill(package=package),
        'current': package,
    }


def test_contextvar_isolates_eight_threads_alternating_packages():
    """用模块级全局实现的「当前包」在这条用例下必红：线程之间会互相覆盖。"""
    expected = {A: _expected(A), B: _expected(B)}
    assert expected[A]['prompt'] != expected[B]['prompt']

    barrier = threading.Barrier(8)
    errors: list[str] = []

    def worker(index: int) -> None:
        package = A if index % 2 == 0 else B
        barrier.wait()
        for _ in range(20):
            with packages.package_context(package):
                seen_current = packages.current_package()
                seen = _read_current_package_data()
            if seen_current != package:
                errors.append(f'{threading.current_thread().name}: current={seen_current} 期望 {package}')
                return
            if seen != expected[package]:
                diff = {key: (seen[key], expected[package][key])
                        for key in expected[package] if seen[key] != expected[package][key]}
                errors.append(f'{threading.current_thread().name}: 读到别的包的数据 {diff}')
                return

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(worker, range(8)))

    assert errors == [], '\n'.join(errors)
    # 主线程自己没设过包 → 必须仍回落默认包（A）
    assert packages.current_package() == A


def test_package_context_restores_on_exception():
    with pytest.raises(RuntimeError):
        with packages.package_context(B):
            assert packages.current_package() == B
            raise RuntimeError('boom')
    assert packages.current_package() == A


# --------------------------------------------------------------------------- #
# 7 依赖零污染
# --------------------------------------------------------------------------- #


def test_core_still_imports_no_host_package():
    assert gate_core_iso.dep_sites(REPO / 'core') == [], 'core/** 出现了对宿主包的 import'
    new_files = sorted((REPO / 'core' / 'packages').glob('*.py'))
    assert {path.name for path in new_files} == {'__init__.py', 'context.py', 'registry.py'}


# --------------------------------------------------------------------------- #
# 8 解析不依赖 configure()（裸 core 子进程）
# --------------------------------------------------------------------------- #


def test_bare_core_resolves_a_package_without_the_host():
    """子进程只 import core（不 import 宿主）：按包名解析提示词/词表/图表都要成功。"""
    script = (
        'from core.packages import load_package, current_package\n'
        'from core.prompts import registry as prompts\n'
        'from core.tools import vocabulary\n'
        'from core.charts import registry as charts\n'
        'pkg = load_package("demo_b")\n'
        'print("BARE", pkg.name, pkg.default_profile, len(prompts.prompts(package="demo_b")),\n'
        '      list(vocabulary.localities(package="demo_b")), charts.ids(package="demo_b"),\n'
        '      current_package())\n'
    )
    done = subprocess.run([sys.executable, '-W', 'ignore', '-c', script], cwd=str(REPO),
                          capture_output=True, text=True, encoding='utf-8', timeout=180)
    assert done.returncode == 0, done.stderr
    line = [row for row in done.stdout.splitlines() if row.startswith('BARE')][0]
    assert line == ("BARE demo_b demo_b 10 ['景区片区', '中心城区'] "
                    "['sentiment', 'daily', 'platform'] anshun_monthly")


# --------------------------------------------------------------------------- #
# 9 LRU 容量 + 指纹进键
# --------------------------------------------------------------------------- #


def test_load_cache_is_bounded_and_keyed_by_fingerprint(tmp_path, monkeypatch):
    assert package_registry.cache_info().maxsize == 8
    packages_root = tmp_path / 'packages'
    _make_package(packages_root, 'fp_pkg', 'pack-a')
    monkeypatch.setenv('REPORT_PACKAGES_ROOT', str(packages_root))

    first = packages.load_package('fp_pkg')
    assert packages.load_package('fp_pkg') is first, '未改文件时不该重新加载'

    target = packages_root / 'fp_pkg' / 'template.json'
    stamp = target.stat()
    target.write_bytes(json.dumps({'vocabulary': {'localities': {'新区': ['x']}}},
                                  ensure_ascii=False).encode('utf-8'))
    if target.stat().st_mtime_ns == stamp.st_mtime_ns:      # 文件系统时间粒度保护
        import os
        os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000))
    second = packages.load_package('fp_pkg')
    assert second is not first, '指纹没进缓存键：改了 template.json 仍返回旧加载结果'
    assert list(second.template['vocabulary']['localities']) == ['新区']
