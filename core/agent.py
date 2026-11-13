"""提示词薄壳：客户注入点 + 既有公开名。文本与角色全部在 `packages/<pkg>/prompts/`。

`core/prompts/registry.py` 负责读盘与结构校验（`app/__init__.py` 在首次 import 时 configure 一次）；
本模块只做三件事：把 4 个数据对象绑成同名全局、把 5 个旧文本常量降级为别名、保留 3 个策略函数。
这三个函数的函数体自 S4 起一字未改——39 个 `get_prompt` 调用点全靠它们。
"""
from dataclasses import dataclass
from core.prompts import registry as _registry

@dataclass(frozen=True)
class AgentDefinition:
    role_id: str
    responsibility: str
    boundary: str
    output: str

# 角色定义：状态数据 → frozen dataclass（`model_client.py:73` 用属性访问）
AGENT_DEFINITIONS = {role_id: AgentDefinition(role_id, spec['responsibility'], spec['boundary'], spec['output'])
                     for role_id, spec in _registry.roles().items()}

# 提示词与结构化策略：唯一的家在客户包；这里只持有加载结果的副本
AGENT_PROMPTS = _registry.prompts()
TEMPLATE_POLICY = _registry.template_policy()
REPORT_PROMPT_PROFILES = _registry.report_profiles()
DEFAULT_PROMPT_PROFILE = _registry.default_profile()

# 覆盖可见性：键 → 实际来源（'package' 客户包文件 / 'base' 基座兜底）；只读，供排障与测试
provenance = _registry.provenance

# 旧文本常量保留为别名（全仓 0 消费，但保留零成本；见 docs/team/任务分解-S5.md §7 D2）
RISK_COMPARISON_PROMPT = AGENT_PROMPTS['historical_researcher.plan']
RESEARCH_PROMPT = AGENT_PROMPTS['historical_researcher.research']
ANALYSIS_PROMPT = AGENT_PROMPTS['writer.analysis']
OUTLOOK_PROMPT = AGENT_PROMPTS['writer.outlook']
TEMPLATE_INSTRUCTION = AGENT_PROMPTS['template_analyst.template']

def prompt_profile(task_metadata=None, template=None):
    metadata = task_metadata or {}
    template = template or {}
    selected = metadata.get('writer_prompt_profile') or template.get('metadata', {}).get('writer_prompt_profile') or DEFAULT_PROMPT_PROFILE
    if selected not in REPORT_PROMPT_PROFILES:
        raise ValueError('unknown_writer_prompt_profile:' + str(selected))
    return selected

def get_prompt(key, profile=DEFAULT_PROMPT_PROFILE):
    if profile not in REPORT_PROMPT_PROFILES:
        raise ValueError('unknown_writer_prompt_profile:' + str(profile))
    if key not in AGENT_PROMPTS:
        raise KeyError('unknown_agent_prompt:' + key)
    overrides = REPORT_PROMPT_PROFILES[profile]
    value = overrides[key] if key in overrides else AGENT_PROMPTS[key]
    if not isinstance(value,str) or not value.strip():
        raise ValueError('invalid_agent_prompt:' + key)
    return value

def prompt_fingerprint(profile=DEFAULT_PROMPT_PROFILE, prefixes=('writer.', 'historical_researcher.')):
    """Machine prose is regenerated when its chosen writing instructions change."""
    import hashlib,json
    prompts={key:get_prompt(key,profile) for key in AGENT_PROMPTS if key.startswith(prefixes)}
    return hashlib.sha256(json.dumps(prompts,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
