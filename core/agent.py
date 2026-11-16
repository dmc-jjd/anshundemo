"""提示词薄壳：客户注入点 + 既有公开名。文本与角色全部在 `packages/<pkg>/prompts/`。

三不变量（`core/packages/` 同一套，逐条都是硬约束）：
    ① 模块级「包派生常量」必须为零——本模块**没有** `AGENT_PROMPTS = ...` 这种 import 期
       求值的快照；5 个旧名由 PEP 562 的 `__getattr__` 惰性给出（读一次缓存一次，并各发一次
       `DeprecationWarning`）。新代码请用 `get_prompt(..., package=...)` 或
       `core.packages.load_package(pkg)`；旧名只为「39 个 `get_prompt` 调用点不必一次全改」而留。
    ② `configure*()` 只许启动期 / 子进程初始化期调用，绝不许请求期切包；
    ③ `package` 不许进 artifact payload（M1 边界）。

为什么不保留模块级快照（这是 M1 的核心）：
    旧实现 `AGENT_PROMPTS = _registry.prompts()` 在**首次 import 期**求值并冻结成当时被
    configure 的那个包。两个包并存时，B 包的模型系统提示词会是 A 的——产物顺利生成、不报错、
    测试全绿。现在每个函数都按 `package`（缺省 = 当前上下文，见 `core.packages.context`）
    解析，且解析结果由 `PackageLoad` 按「包名 + 指纹」缓存，改文件即失效。

三个策略函数（`prompt_profile` / `get_prompt` / `prompt_fingerprint`）的**入参顺序与错误语义**
继承 S4 以来的一字未改版本；新增参数全部是尾部关键字（`package=`），39 个调用点零改动。
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

from core.packages import registry as _packages
from core.prompts import registry as _registry


@dataclass(frozen=True)
class AgentDefinition:
    role_id: str
    responsibility: str
    boundary: str
    output: str


#: 覆盖可见性：键 → 实际来源（'package' 客户包文件 / 'base' 基座兜底）；只读，供排障与测试。
provenance = _registry.provenance


def _resolved(package: str | None = None):
    """当前（或指定）包的加载结果；缓存键含包名 + 指纹，见 `core.packages.registry`。"""
    return _packages.load(package)


def prompt_profile(task_metadata=None, template=None, package=None):
    """选定的 writer 提示词 profile：任务元数据 → 模板元数据 → 该包默认 profile。"""
    metadata = task_metadata or {}
    template = template or {}
    resolved = _resolved(package)
    selected = (metadata.get('writer_prompt_profile')
                or template.get('metadata', {}).get('writer_prompt_profile')
                or resolved.default_profile)
    if selected not in resolved.report_profiles:
        raise ValueError('unknown_writer_prompt_profile:' + str(selected))
    return selected


def get_prompt(key, profile=None, package=None):
    """取一条提示词：`package` 缺省 = 当前上下文；`profile` 缺省 = 该包默认 profile。

    错误语义逐字保留：未知 profile → `ValueError('unknown_writer_prompt_profile:...')`，
    未知键 → `KeyError('unknown_agent_prompt:...')`，空值 → `ValueError('invalid_agent_prompt:...')`。
    """
    resolved = _resolved(package)
    selected = profile or resolved.default_profile
    profiles = resolved.report_profiles
    if selected not in profiles:
        raise ValueError('unknown_writer_prompt_profile:' + str(selected))
    prompts = resolved.agent_prompts
    if key not in prompts:
        raise KeyError('unknown_agent_prompt:' + key)
    overrides = profiles[selected]
    value = overrides[key] if key in overrides else prompts[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError('invalid_agent_prompt:' + key)
    return value


def prompt_fingerprint(profile=None, prefixes=('writer.', 'historical_researcher.'), package=None):
    """Machine prose is regenerated when its chosen writing instructions change."""
    import hashlib
    import json

    resolved = _resolved(package)
    selected = profile or resolved.default_profile
    prompts = {key: get_prompt(key, selected, package)
               for key in resolved.agent_prompts if key.startswith(prefixes)}
    return hashlib.sha256(json.dumps(prompts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


# --------------------------------------------------------------------------- #
# 旧公开名（PEP 562 惰性代理）：只为兼容，别在新代码里用
# --------------------------------------------------------------------------- #

def _lazy_agent_definitions():
    return _resolved().agent_definitions


def _lazy_agent_prompts():
    return _resolved().agent_prompts


def _lazy_template_policy():
    return _resolved().template_policy


def _lazy_report_profiles():
    return _resolved().report_profiles


def _lazy_default_profile():
    return _resolved().default_profile


def _lazy_risk_comparison_prompt():
    return get_prompt('historical_researcher.plan')


def _lazy_research_prompt():
    return get_prompt('historical_researcher.research')


def _lazy_analysis_prompt():
    return get_prompt('writer.analysis')


def _lazy_outlook_prompt():
    return get_prompt('writer.outlook')


def _lazy_template_instruction():
    return get_prompt('template_analyst.template')


_LAZY = {
    'AGENT_DEFINITIONS': _lazy_agent_definitions,
    'AGENT_PROMPTS': _lazy_agent_prompts,
    'TEMPLATE_POLICY': _lazy_template_policy,
    'REPORT_PROMPT_PROFILES': _lazy_report_profiles,
    'DEFAULT_PROMPT_PROFILE': _lazy_default_profile,
    # 旧文本常量（全仓 0 消费，保留零成本；见 docs/team/任务分解-S5.md §7 D2）
    'RISK_COMPARISON_PROMPT': _lazy_risk_comparison_prompt,
    'RESEARCH_PROMPT': _lazy_research_prompt,
    'ANALYSIS_PROMPT': _lazy_analysis_prompt,
    'OUTLOOK_PROMPT': _lazy_outlook_prompt,
    'TEMPLATE_INSTRUCTION': _lazy_template_instruction,
}

__all__ = ['AgentDefinition', 'provenance', 'prompt_profile', 'get_prompt',
           'prompt_fingerprint', *_LAZY]


def __getattr__(name: str):
    """旧名惰性代理：第一次读到才解析当前包，随后缓存到模块字典（同一对象，non-copy）。

    缓存到模块字典是有意的：`app.model_client.AGENT_DEFINITIONS is app.agent.AGENT_DEFINITIONS`
    被 `tests/test_s5_prompt_parity.py:43` 钉死，每次 getattr 现算会破坏这条同一性；
    而 `REPORT_PROMPT_PROFILES` 上的原地 mutation（monkeypatch.setitem）也必须对
    `get_prompt` 生效，所以必须是**同一个 dict 对象**，不是副本。
    """
    factory = _LAZY.get(name)
    if factory is None:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    value = factory()
    globals()[name] = value
    warnings.warn(f'core.agent.{name} 是包派生值的旧快照出口，将在下个里程碑移除；'
                  f'请改用 get_prompt(..., package=...) 或 core.packages.load_package(pkg)',
                  DeprecationWarning, stacklevel=2)
    return value
