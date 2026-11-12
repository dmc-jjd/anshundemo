"""工具执行器：策略校验 + 预算 + 子进程隔离（WP-S8-L3，自 `app/tool_executor.py` 逐字搬迁）。

本层四处改造（`docs/team/任务分解-S8.md` §3-1 / §3-3）：
1. 包目录不再从宿主 `config` 拿——基座不 import 宿主；改 `paths.package_dir()`
   （宿主在 `__init__` 注入，与 `data_root` 同一个注入面）。
2. `_default_policy()` 里 `load_manifest(...)` 必须**函数内**取包目录：模块级求值会让
   「先 import core、后 import 宿主」的顺序炸（S7 B3 同理由）。
3. `.tool` 的 import 下沉到函数内：spawn 子进程 unpickle `_run_in_process` 时会先执行本模块顶层，
   而 `core/tool.py` 顶层读 5 个 `vocabulary.*`；`core/__init__.py` 是空的，此刻尚未 configure。
   先把 `_configure_package(...)` 跑完再触达 `core.tool`，子进程才不会 `package_not_configured`
   （S6 §0.8 / F5 陷阱的镜像：表现为每个工具调用都超时、工件全空，而门禁仍绿）。
4. 子进程与父进程拿到的是**同一张已扩表目录**：`writer_tools` / `historical_web` 已在 L1 进基座，
   故 `_tool_specs()` 的扩表与宿主组合根 `app/tool.py` 逐字等价（先 writer 后 web，21 项不变）。
"""
from __future__ import annotations
import asyncio,time,uuid,multiprocessing
from dataclasses import dataclass
from pathlib import Path
from .schemas import ToolCall,ToolResult
from . import paths
from core.manifest import load_manifest
from core.ports import (REJECT_BUDGET_EXCEEDED,REJECT_FROZEN_FACTS,REJECT_PHASE_NOT_ALLOWED,
                        REJECT_TOOL_NOT_ALLOWED,ToolPolicy)
from core.tools import hints

def _tool_specs():
    """已扩表的工具清单（延迟 import，见模块 docstring 第 3 点）。

    `writer_tools` / `historical_web` 已在 L1 进基座，故这里的扩表与宿主组合根
    （`app/tool.py`）逐字等价：先 writer 后 web 的并入顺序不变，`G-SPECS` 的 21 项不变。
    """
    from .tool import get_tool_specs
    from . import historical_web,writer_tools
    return get_tool_specs(extra_modules=(writer_tools,historical_web))

def _tool_handler(name):
    _tool_specs()
    from .tool import HANDLERS
    return HANDLERS[name]

@dataclass
class RunContext:
    store: object
    task_id: str
    phase: str = 'processing'
    timeout: float = 60
    model_adapter: object = None
    policy: ToolPolicy | None = None

_POLICY=None
def _default_policy():
    """客户包的策略：`capabilities.require` 剪枝 + `features.*` 能力开关。

    两层叠加：
    - `capabilities.require` 回答「这份报告要哪些产物」→ 反推可达工具集
    - `features.<能力>.enabled: false` 回答「某个能力开不开」→ 整组工具退出白名单

    于是「去重/分类/研判不必每份报告都跑」由客户包数据决定，不由执行器里的 if 决定。
    未声明 require / 未声明 features 时，行为与改造前完全一致。
    """
    global _POLICY
    if _POLICY is None:
        manifest=load_manifest(paths.package_dir())
        policy=manifest.policy
        required=manifest.required_capabilities
        features=manifest.features
        if required or features:
            from core.tools.registry import resolve_tools
            narrowed=resolve_tools(required, features)
            base=set(policy.allow) if policy.allow else narrowed
            policy=ToolPolicy(allow=frozenset(base&narrowed),
                              phases=policy.phases,budgets=policy.budgets)
        _POLICY=policy
    return _POLICY

def _ref_key(name,arguments):
    spec=hints.REF_KEY.get(name)
    return spec[1]+str(arguments.get(spec[0])) if spec else name

def _reject(context,call,reason):
    context.store.append_event(context.task_id,{'type':'tool_policy_rejected','tool':call.tool_name,'phase':context.phase,'reason':reason})
    return ToolResult(status='error',error_code=reason)

def _run_in_process(name,arguments,root,task_id,conn,package_dir=None):
    """子进程入口：**显式配置客户包**，不依赖 import 副作用。

    为什么必须显式（S8 迁移前置）：
    现状能跑，是因为 `from .storage import Store` 会触发 `app/__init__.py` 里的四次
    configure。一旦 tool_executor 搬进 core，子进程 import 的是 `core.*`，
    `core/__init__.py` 是空文件 —— 工具模块级读的 `vocabulary.*` 会抛
    `package_not_configured`，表现为**每次工具调用都超时、工件全空，而门禁哈希仍稳定**
    （S6 F5 陷阱的镜像）。

    所以这里显式传 `package_dir`，让子进程自己把四个注册表配好，不赌 import 顺序。
    """
    from .storage import Store
    try:
        if package_dir is not None:
            _configure_package(Path(package_dir))
        ctx=RunContext(Store(root),task_id)
        result=_tool_handler(name)(arguments,ctx)
        conn.send(('ok',result.model_dump()))
    except Exception as e:
        conn.send(('error',{'error_code':type(e).__name__,'message':str(e)}))
    finally: conn.close()


def _configure_package(package_dir):
    """按客户包路径配置四个注册表（幂等）。子进程里调用，不依赖 app 的 import 副作用。"""
    from core.manifest import load_manifest
    from core.paths import configure_data_root
    from core.tools import vocabulary
    from core.charts import registry as chart_registry
    from core.skills import registry as skill_registry
    from core.prompts import registry as prompt_registry

    manifest = load_manifest(package_dir)
    root = Path(package_dir).resolve().parent.parent
    vocabulary.configure(package_dir)
    chart_registry.configure(package_dir)
    skill_registry.configure(package_dir, root / "skills")
    prompt_registry.configure(package_dir)
    configure_data_root(root / manifest.data_root if hasattr(manifest, "data_root") else root / "data")
    return manifest


def _bounded_run(name,arguments,root,task_id,timeout,package_dir=None):
    parent,child=multiprocessing.Pipe(duplex=False)
    proc=multiprocessing.get_context('spawn').Process(target=_run_in_process,args=(name,arguments,root,task_id,child,package_dir))
    proc.start(); child.close()
    ready=parent.poll(timeout)
    if not ready:
        proc.terminate(); proc.join(5)
        if proc.is_alive(): proc.kill(); proc.join()
        parent.close()
        return ToolResult(status='error',error_code='timeout',warnings=['worker terminated after timeout'])
    if ready:
        status,value=parent.recv(); parent.close()
        proc.join(5)
        return ToolResult.model_validate(value) if status=='ok' else ToolResult(status='error',error_code=value['error_code'],warnings=[value['message']])
    parent.close(); return ToolResult(status='error',error_code='worker_exit',warnings=[f'worker exit code {proc.exitcode}'])

async def execute_tool(call:ToolCall,context:RunContext)->ToolResult:
    start=time.monotonic(); state=context.store.get_task(context.task_id)
    specs={x.name:x for x in _tool_specs()}
    if call.tool_name not in specs: return ToolResult(status='error',error_code='unknown_tool')
    policy=context.policy or _default_policy()
    if call.tool_name not in set(policy.allow)|set(policy.phases.get(context.phase,frozenset())):
        declared=set(policy.allow)|{x for tools in policy.phases.values() for x in tools}
        return _reject(context,call,REJECT_PHASE_NOT_ALLOWED if call.tool_name in declared else REJECT_TOOL_NOT_ALLOWED)
    schema=specs[call.tool_name].arguments_schema
    if any(key not in call.arguments for key in schema.get('required',[])):
        return ToolResult(status='error',error_code=hints.REQUIRED_ERROR_CODE.get(call.tool_name,'missing_required_argument'))
    for key,value in call.arguments.items():
        if key.endswith('_ref') and isinstance(value,str) and value not in state.result_refs.values() and not context.store.artifact_belongs_to_task(value,context.task_id):
            return ToolResult(status='error',error_code='unauthorized_input_ref')
    if 'path' in call.arguments:
        allowed={state.metadata.get('input_path'),*state.metadata.get('paths',[])}
        if allowed-{None} and call.arguments.get('path') not in allowed: return ToolResult(status='error',error_code='path_not_in_task_inputs')
    for tool,scopes in hints.SCOPE_ENUM.items():
        if call.tool_name==tool and call.arguments.get('scope') not in scopes:
            return ToolResult(status='error',error_code=hints.SCOPE_ERROR_CODE.get(tool,'unapproved_filter_scope'))
    writer_readonly=call.tool_name in policy.phases.get(context.phase,())
    budget=policy.budget(context.phase)
    if writer_readonly:
        if state.metadata.get('writer_tool_calls',0)>=budget:return _reject(context,call,REJECT_BUDGET_EXCEEDED)
    elif state.tool_calls>=budget: return _reject(context,call,REJECT_BUDGET_EXCEEDED)
    guard=hints.REQUIRES_FROZEN_FACTS.get(call.tool_name)
    if guard and not state.fact_ref: return ToolResult(status='error',error_code=guard)
    if state.fact_ref and specs[call.tool_name].mutates_facts: return ToolResult(status='error',error_code=REJECT_FROZEN_FACTS)
    signature=call.idempotency_key or f'{specs[call.tool_name].version}:{call.tool_name}:{call.arguments}:{call.input_refs}'
    if writer_readonly:signature+=f':{state.fact_ref}:{state.metadata.get("report_parameters_ref","")}'
    prior=state.metadata.get('tool_results',{}).get(signature)
    if prior:
        cached=ToolResult.model_validate(prior)
        if cached.data_ref:
            state.result_refs[_ref_key(call.tool_name,call.arguments)]=cached.data_ref
            context.store.put_task(state,state.revision)
        return cached
    state.tool_calls+=1
    if writer_readonly:state.metadata['writer_tool_calls']=state.metadata.get('writer_tool_calls',0)+1
    context.store.put_task(state,state.revision)
    context.store.append_event(context.task_id,{'type':'tool_start','tool':call.tool_name,'reason':call.reason,'arguments':call.arguments,'call_id':call.call_id})
    try:
        timeout=hints.TIMEOUT_S.get(call.tool_name,context.timeout)
        result=await asyncio.to_thread(_bounded_run,call.tool_name,call.arguments,context.store.root,context.task_id,timeout,str(paths.package_dir()))
    except Exception as e: result=ToolResult(status='error',error_code=type(e).__name__,warnings=[str(e)])
    result.elapsed_ms=int((time.monotonic()-start)*1000)
    state=context.store.get_task(context.task_id)
    state.metadata.setdefault('tool_results',{})[signature]=result.model_dump()
    if result.data_ref:
        if call.tool_name in hints.REF_KEY: state.result_refs[_ref_key(call.tool_name,call.arguments)]=result.data_ref
        else: state.result_refs[call.tool_name]=result.data_ref
        alias=hints.REF_ALIAS.get(call.tool_name)
        if alias and str(call.arguments.get(alias[0],alias[1]))==alias[1]: state.result_refs[alias[2]]=result.data_ref
    context.store.put_task(state,state.revision)
    context.store.append_event(context.task_id,{'type':'tool_result','tool':call.tool_name,**result.model_dump()})
    return result

