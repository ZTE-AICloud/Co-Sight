"""
Agent tool shim
===============
提供 Agent 函数，通过 `cosight -p` 调用子 Agent。
子 Agent 定义在 agents/ 目录下，作为系统提示注入。

用法：
    from tools import Agent
    result = Agent(
        mode="auto",
        description="提取指标",
        subagent_type="ExtractionAgent",
        prompt="扫描目录，提取指标",
    )

观测性：
    设置环境变量 SKILLX_CURRENT_TASK_DIR 后，每次 Agent() 调用会把完整调用
    上下文（system prompt / user prompt / stdout / stderr / returncode 等）
    落盘到 {SKILLX_CURRENT_TASK_DIR}/_debug/agent_*.txt。这是 ExtractionAgent /
    ProposalAgent 等失败时定位"是 LLM 返回为空 / 还是格式错误 / 还是调用失败"
    的关键审计依据。

    _dump_llm_call() 是对 HTTP 直调（call_llm_api / call_llm_json）的同一套落盘机制，
    写入 {SKILLX_CURRENT_TASK_DIR}/_debug/agent_<label>_<ts>_<seq>.txt，包含
    RAW RESPONSE 和 PARSED RESULT 段，与 subagent 路径同目录便于全局排查。
"""

import os
import re
import threading
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from agent_runner import get_runner as _get_agent_runner

# ─── Tool Use 审计常量(2026-07-31 增量)──────────────────────────────────
#
# _summarize_tool_use_from_jsonl() 用这些常量把 LLM 实际访问的路径按"业务标签"
# 分类(满足 proposal agent 3 数据源审计需求)。所有标签都是**业务无关的子串**,
# 避免硬编码 phase1/phase2/RAN- 等业务目录名(skillx-alpha-generic.md §2.1)。
#
# 实际业务场景需要不同标签时,调用方可在 Agent() 内部把 subagent_type 映射
# 到 _TOOL_USE_CATEGORIES_OVERRIDE(预留,默认空);当前用 subagent_type 启发式。

# 默认:所有 path 只要含这些子串就归到对应类(顺序敏感 — 先匹配先赢)
_DEFAULT_PATH_CATEGORIES: list = [
    # proposal agent 必读数据源(2026-08-10 修正)
    # score_analyzer_report_round_x.md 已含 skill_diff 内容 → 只强制 score_analyzer_report;
    # result_diff / skill_diff 单独读是冗余的,不再强制(读了不违规,不读不计 MISSING)。
    ("required::score_analyzer_report", ("score_analyzer_report",)),
    ("required::consume_lib",  ("consume_lib", "consume-library", "references/methodology")),
    # 中性证据(读了更好,不强制)
    ("evidence_report",        ("result_diff_report", "skill_diff_round", "skill_diff_")),
    # Skill 自身(中性 — 不计入"未访问清单文件"违规)
    ("skill_file",             ("SKILL.md", "/scripts/", "/references/", "/templates/")),
]

# subagent_type 启发式:proposal-agent 类(名字含 proposal)→ 启用 required 审计标签
def _resolve_path_categories(subagent_type: str) -> list:
    """根据 subagent_type 返回路径分类规则。

    业务无关:不读 subagent_type 是否为"proposal-agent"硬字符串,而是
    用 'proposal'/'optimize' 子串启发式(任何叫 *proposal* 的子 Agent
    都会自动套用 required 标签 — 满足未来同类需求)。
    """
    if subagent_type and re.search(r"proposal|optim", subagent_type, re.IGNORECASE):
        return _DEFAULT_PATH_CATEGORIES
    # 其它子 Agent 只用中性 skill_file 标签(避免误判)
    return [c for c in _DEFAULT_PATH_CATEGORIES if c[0] == "skill_file"]


def _categorize_path(path: str, categories: list) -> str:
    """把路径归到第一个匹配的类,无匹配返回 'other'。"""
    if not path:
        return "other"
    p = str(path)
    for label, needles in categories:
        for needle in needles:
            if needle and needle in p:
                return label
    return "other"

# ─── _debug 落盘工具 ──────────────────────────────────────────────────────

_AGENT_CALL_COUNTER = 0
_AGENT_CALL_LOCK = threading.Lock()


def _next_agent_call_seq() -> int:
    """全局递增序号，确保同一秒内的多次调用落盘文件不冲突。"""
    global _AGENT_CALL_COUNTER
    with _AGENT_CALL_LOCK:
        _AGENT_CALL_COUNTER += 1
        return _AGENT_CALL_COUNTER


def _resolve_debug_dir() -> Optional[Path]:
    """从 SKILLX_CURRENT_TASK_DIR 推断 _debug 落盘目录。

    未设置或目录无法创建时返回 None，落盘流程被跳过（不影响主链路）。
    """
    task_dir = os.environ.get("SKILLX_CURRENT_TASK_DIR", "").strip()
    if not task_dir:
        return None
    debug = Path(task_dir) / "_debug"
    try:
        debug.mkdir(parents=True, exist_ok=True)
        return debug
    except Exception:
        return None


def _dump_agent_call(
    debug_dir: Optional[Path],
    subagent_type: str,
    description: str,
    system_prompt: str,
    user_prompt: str,
    stdout: str,
    stderr: str,
    returncode: Optional[int],
    duration_sec: float,
    timeout: Optional[int],
    settings_path: Optional[str],
    exception: Optional[str],
    raw_jsonl: Optional[str] = None,
) -> Optional[Path]:
    """把 Agent 调用的完整上下文写到 _debug 文件，返回文件路径。

    raw_jsonl(可选):当 cosight -p 以 --output-format stream-json 调用时,
    完整 jsonl 流(每行一个事件)。落盘后,`_debug` 文件可 grep tool_use 路径
    验证 LLM 是否真读了清单文件。
    """
    if debug_dir is None:
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    seq = _next_agent_call_seq()
    safe_type = re.sub(r"[^A-Za-z0-9_.-]", "_", subagent_type)[:40]
    fname = f"agent_{safe_type}_{timestamp}_{os.getpid()}_{seq:04d}.txt"
    target = debug_dir / fname

    # 2026-07-31 增量:从 raw_jsonl 解析 LLM 实际访问过的文件/命令,
    # 写到独立 ## TOOL USE SUMMARY 段(审计 LLM 是否真读了清单文件)。
    # raw_jsonl 为空(text 模式)/解析失败 → 段不写,不阻塞主落盘。
    # subagent_type 用于路径分类启发式(proposal/optim 类 Agent 启用 required 标签)
    tool_summary_text = _summarize_tool_use_from_jsonl(raw_jsonl, subagent_type=subagent_type) if raw_jsonl else ""

    try:
        with target.open("w", encoding="utf-8") as fp:
            fp.write(f"# subagent_type : {subagent_type}\n")
            fp.write(f"# description   : {description}\n")
            fp.write(f"# timestamp     : {datetime.now().isoformat()}\n")
            fp.write(f"# pid           : {os.getpid()}\n")
            fp.write(f"# seq           : {seq}\n")
            fp.write(f"# duration_sec  : {duration_sec:.2f}\n")
            fp.write(f"# returncode    : {returncode}\n")
            fp.write(f"# timeout       : {timeout}\n")
            fp.write(f"# settings_path : {settings_path}\n")
            fp.write(f"# exception     : {exception or '(none)'}\n")
            fp.write("\n## SYSTEM PROMPT (begin)\n")
            fp.write(system_prompt or "")
            fp.write("\n## SYSTEM PROMPT (end)\n")
            fp.write("\n## USER PROMPT (begin)\n")
            fp.write(user_prompt or "")
            fp.write("\n## USER PROMPT (end)\n")
            fp.write("\n## STDOUT (begin)\n")
            fp.write(stdout or "")
            fp.write("\n## STDOUT (end)\n")
            fp.write("\n## STDERR (begin)\n")
            fp.write(stderr or "")
            fp.write("\n## STDERR (end)\n")
            if raw_jsonl:
                fp.write("\n## RAW JSONL STREAM (begin)\n")
                fp.write(raw_jsonl)
                fp.write("\n## RAW JSONL STREAM (end)\n")
            if tool_summary_text:
                fp.write("\n## TOOL USE SUMMARY (begin)\n")
                fp.write(tool_summary_text)
                fp.write("\n## TOOL USE SUMMARY (end)\n")
        return target
    except Exception as e:
        # 落盘失败不能影响主链路，只打印警告
        print(f"  ⚠️ [Agent] 调用日志落盘失败: {e}")
        return None


def _summarize_tool_use_from_jsonl(
    raw_jsonl: str,
    subagent_type: str = "",
) -> str:
    """从 cosight -p --output-format stream-json 的 jsonl 流里抽出 LLM
    实际访问过的文件/命令,生成可审计的纯文本摘要。

    输出格式(供 _dump_agent_call 落盘到 ## TOOL USE SUMMARY 段):
        Counter:
          read=5 edit=2 write=0 bash=11
        Files accessed (Read/Edit/Write):
          /path/to/SKILL.md  [skill_file]
          /path/to/result_diff_report_*.md  [required::result_diff]
        Bash commands:
          ls -la
          cat foo.py | head -50
        Required-data-source access (only for proposal/optimize Agent):
          result_diff  : 1 hits
          skill_diff   : 2 hits
          consume_lib  : 0 hits  ⚠️ MISSING
        (end)

    实现要点:
    - 解析失败 → 返回 ''(主调用方 _dump_agent_call 会跳过该段,不阻塞落盘)
    - 路径去重(保序),命令去重(保首现顺序)
    - 路径分类走 _resolve_path_categories(subagent_type) 业务无关启发式
    - 解析时间 < 100ms(对 ~5MB jsonl 单次线性扫);不预编译正则,函数内常量
    """
    if not raw_jsonl or not raw_jsonl.strip():
        return ""

    categories = _resolve_path_categories(subagent_type)

    files_accessed: list = []     # [(path, tool_name, category)]
    bash_commands: list = []      # [command_str]
    tool_counter: Counter = Counter()

    try:
        for line in raw_jsonl.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue

            # ── A) Anthropic content_block 事件:tool_use 块
            # 形态 1:{"type":"content_block_start","content_block":{"type":"tool_use",...}}
            cb = obj.get("content_block")
            if isinstance(cb, dict) and cb.get("type") == "tool_use":
                tool_name = cb.get("name", "")
                inp = cb.get("input") or {}
                _record_tool_invocation(tool_name, inp, files_accessed, bash_commands, tool_counter, categories)
                continue

            # 形态 2:{"type":"message","message":{"content":[{"type":"tool_use",...}, ...]}}
            msg = obj.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_name = block.get("name", "")
                            inp = block.get("input") or {}
                            _record_tool_invocation(tool_name, inp, files_accessed, bash_commands, tool_counter, categories)

            # 形态 3:{"type":"assistant","content":[{"type":"tool_use",...}, ...]}
            if obj.get("type") == "assistant":
                content = obj.get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_name = block.get("name", "")
                            inp = block.get("input") or {}
                            _record_tool_invocation(tool_name, inp, files_accessed, bash_commands, tool_counter, categories)
    except Exception as e:
        # 解析失败 → 返回空串,主调用方 _dump_agent_call 会跳过该段
        print(f"  ⚠️ [tool-use summary] 解析失败: {type(e).__name__}: {e}", file=__import__('sys').stderr)
        return ""

    if not tool_counter and not files_accessed and not bash_commands:
        return ""  # jsonl 里没 tool_use,落空段没意义

    # ── 汇总输出
    out: list = []
    out.append("Counter:")
    for k in ("Read", "Edit", "Write", "Bash", "Grep", "Glob", "NotebookEdit"):
        if tool_counter.get(k):
            out.append(f"  {k.lower()}={tool_counter[k]}")
    out.append("")

    if files_accessed:
        out.append("Files accessed (Read/Edit/Write):")
        seen = set()
        for path, _tool, cat in files_accessed:
            if path in seen:
                continue
            seen.add(path)
            out.append(f"  {path}  [{cat}]")
        out.append("")

    if bash_commands:
        out.append("Bash commands:")
        seen_cmds = set()
        for cmd in bash_commands:
            if cmd in seen_cmds:
                continue
            seen_cmds.add(cmd)
            # 命令截断到 200 字,保留可读性
            out.append(f"  {cmd[:200]}")
        out.append("")

    # required 标签命中(只对 proposal/optim 类 Agent 启用)
    if any(c[0].startswith("required::") for c in categories):
        out.append("Required-data-source access (proposal/optimize audit):")
        cat_hits: Counter = Counter(cat for _p, _t, cat in files_accessed)
        for label, _needles in categories:
            if not label.startswith("required::"):
                continue
            short = label.split("::", 1)[1]
            n = cat_hits.get(label, 0)
            mark = "" if n > 0 else "  ⚠️ MISSING"
            out.append(f"  {short:<14}: {n} hits{mark}")
        out.append("")

    out.append("(end)")
    return "\n".join(out)


def _record_tool_invocation(
    tool_name: str,
    inp: dict,
    files_accessed: list,
    bash_commands: list,
    tool_counter: Counter,
    categories: list,
) -> None:
    """从单个 tool_use 块抽 path / command,记入对应桶。"""
    tool_counter[tool_name] += 1
    if not isinstance(inp, dict):
        return

    if tool_name in ("Read", "Edit", "Write", "NotebookEdit"):
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        if path:
            files_accessed.append((path, tool_name, _categorize_path(path, categories)))
    elif tool_name in ("Grep", "Glob"):
        # Grep/Glob 也算文件访问(按 path 字段),但归类为 'search'
        path = inp.get("file_path") or inp.get("path") or inp.get("pattern") or ""
        if path:
            files_accessed.append((path, tool_name, "search"))
    elif tool_name == "Bash":
        cmd = inp.get("command") or ""
        if cmd:
            bash_commands.append(cmd)
            # 顺便从 cat/grep/find/ls 命令里粗抽 path(用于"读了哪些文件"审计)
            # 排除纯数字 / short flag(防 -50/--foo/-la 被误识别为路径)
            for hit in re.findall(r"(?:^|\s)(?:cat|less|head|tail|grep|find|ls)\s+(--?\S+|[^\s|;&]+)", cmd):
                if hit.startswith("-"):
                    continue  # 跳过所有 flag: -l / -la / --color / -n 5
                files_accessed.append((hit, "Bash", _categorize_path(hit, categories)))


# ─── 子 Agent 定义加载 ────────────────────────────────────────────────────


def _find_agents_dir(start: Optional[Path] = None) -> Path:
    """定位插件根目录（含顶层 `agents/` 或 `.cosight/agents/`）。

    优先用宿主注入的 env（Claude 的 $CLAUDE_PLUGIN_ROOT / Cosight 的 $COSIGHT_PLUGIN_ROOT）;
    未设置时从 start（默认 scripts/）向上找含任一 agents 布局的插件根。
    """
    for env_var in ("CLAUDE_PLUGIN_ROOT", "COSIGHT_PLUGIN_ROOT"):
        env_root = os.environ.get(env_var)
        if env_root:
            r = Path(env_root)
            if (r / "agents").is_dir() or (r / ".cosight" / "agents").is_dir():
                return r
    if start is None:
        start = Path(__file__).resolve().parent  # scripts/
    current = start
    for _ in range(6):
        if (current / "agents").is_dir() or (current / ".cosight" / "agents").is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return start


def _plugins_agents_dir(root: Path) -> Path:
    """解析插件根下的 agents 目录：顶层 `agents/` 优先，否则 `.cosight/agents/`。"""
    top = root / "agents"
    if top.is_dir():
        return top
    return root / ".cosight" / "agents"


def _load_agent_definition(subagent_type: str, project_root: Path, context: Optional[dict] = None) -> str:
    """加载 agents/ 下（或 Cosight 形态 `.cosight/agents/`）的 Agent 定义。

    Args:
        subagent_type: Agent 类型名
        project_root: 项目根目录
        context: 可选的占位符渲染上下文（dict），用于替换 agent definition 中的 {{PLACEHOLDER}}

    Returns:
        渲染后的 agent definition 文本
    """
    agents_dir = _plugins_agents_dir(project_root)
    if not agents_dir.is_dir():
        return ""

    # 尝试多种命名格式
    candidates = [
        f"{subagent_type}.md",
        f"{subagent_type.lower()}.md",
        f"{subagent_type.lower().replace('-', '_')}.md",
        f"{subagent_type.lower().replace('_', '-')}.md",
    ]
    for name in candidates:
        p = agents_dir / name
        if p.exists():
            content = p.read_text(encoding="utf-8")
            if context:
                content = content.format_map(context)
            return content

    # 模糊匹配
    keywords = re.findall(r'[A-Z][a-z]+|[a-z]+|\d+', subagent_type)
    keywords_lower = [k.lower() for k in keywords if k.lower() != 'agent']

    for f in agents_dir.glob("*.md"):
        stem = f.stem.lower()
        stem_words = set(re.findall(r'[a-z]+|\d+', stem))
        if all(kw in stem_words or any(kw in sw for sw in stem_words) for kw in keywords_lower):
            content = f.read_text(encoding="utf-8")
            if context:
                content = content.format_map(context)
            return content

    available = [f.stem for f in agents_dir.glob("*.md")]
    raise FileNotFoundError(
        f"子 Agent 定义未找到: {subagent_type}\n"
        f"可用 Agent: {', '.join(available)}"
    )


# ─── cosight -p 调用 ──────────────────────────────────────────────────────


def _load_project_settings_env() -> dict:
    """返回传递给 claude -p 子进程的额外环境变量。

    Claude 端口：子进程 `claude -p` 直接继承父会话的 os.environ（含
    ANTHROPIC_BASE_URL / AUTH_TOKEN / CLAUDE_PLUGIN_ROOT 等），不需要也不应该
    再注入项目级模型配置（原来为绕过 cosight router 而做的覆盖在本运行时无意义）。
    保留此函数仅维持签名稳定，返回空 dict 即"继承即可"。
    """
    return {}


def _call_claude_pipe(
    system: str,
    prompt: str,
    timeout: Optional[int] = None,
    settings_path: Optional[str] = None,
    output_format: Optional[str] = None,
) -> Tuple[str, str, Optional[int], float, Optional[str], Optional[str]]:
    """通过 `claude -p` 调用 LLM，返回
    (stdout, stderr, returncode, duration_sec, exception_str, raw_jsonl_or_none)。

    raw_jsonl：当 output_format='stream-json' 时,逐行 jsonl 流(便于 _dump_agent_call
    落盘 LLM 中间 assistant 消息 + tool_use blocks);否则为 None(默认 text 模式不记录)。

    将系统提示作为上下文放在用户指令之前，通过 stdin 管道传入。

    超时控制（通用，遵守 COSIGHT.md "orchestrator 执行不设超时" 原则）：
    - 默认无超时（None）：让 LLM 跑完，避免长推理被截断
    - 通过环境变量 `SKILLX_AGENT_TIMEOUT` 可设置上限（秒），例如 1800
    - 调用方也可通过 timeout 参数显式传入

    settings_path（如提供）：通过 `--settings <path>` 注入子 Agent 配置，
        （Claude 端口：子进程继承父会话 settings，无需注入 --settings；保留参数兼容。）

    返回契约：
    - 始终返回 6 元组，**不抛异常**（由 Agent() 统一处理失败情形）
    - returncode=None 表示子进程未启动或异常退出，exception_str 含原因
    - stdout / stderr 已 strip 但保留完整字符（不截断）
    - raw_jsonl: stream-json 模式时为原始 jsonl 字符串(逐行);其他模式为 None

    实现：委托 `agent_runner.get_runner()` 选定的 provider（默认 claude，向后兼容），
    provider 内部含原本的 claude -p 命令构造 / stream-json result 帧解析 / 观测性打印。
    """
    res = _get_agent_runner().run(
        system,
        prompt,
        timeout=timeout,
        settings_path=settings_path,
        output_format=output_format,
    )
    return res.stdout, res.stderr, res.returncode, res.duration_sec, res.exception_str, res.raw_jsonl


# ─── 对外 Agent 函数 ──────────────────────────────────────────────────────


def Agent(
    description: str,
    prompt: str,
    subagent_type: str,
    mode: str = "auto",
    cwd: Optional[str] = None,
    timeout: Optional[int] = None,
    settings_path: Optional[str] = None,
    context: Optional[dict] = None,
    # 🆕 2026-08-01 修:默认 stream-json,让 raw_jsonl 落盘,framework 端能解析真实 tool_use 统计
    # 历史:默认 None(=text 模式)导致 _debug/agent_*.txt 缺 ## TOOL USE SUMMARY 段,
    # 框架看不到 ReadTool/EditTool/WriteTool 真实调用次数,proposal-agent 可用 python3
    # 写文件绕开 Edit 工具统计。stream-json 模式让 cosight CLI 以 jsonl 流输出,
    # _dump_agent_call 解析后落盘真实 tool_use 统计。
    output_format: Optional[str] = "stream-json",
) -> str:
    """
    通过 `claude -p`（--append-system-prompt 注入 agent 定义）调用子 Agent。

    参数：
        description: 任务描述（用于日志）
        prompt: 发给子 Agent 的指令
        subagent_type: 子 Agent 类型，对应 agents/ 下的文件名
        mode: 权限模式（保留参数，当前固定 auto）
        cwd: 工作目录（可选，默认项目根目录）
        timeout: 显式超时秒数（默认 None，**不读 SKILLX_AGENT_TIMEOUT 环境变量**,无限时）
        settings_path: 子 Agent 配置文件路径（可选，注入 `--settings` 参数以覆盖用户级配置）
        context: 占位符渲染上下文（可选 dict），替换 agent definition 中的 {{PLACEHOLDER}}
        output_format: cosight -p 输出格式(可选 None / 'text' / 'stream-json')。
                       当为 'stream-json' 时,_dump_agent_call 会多落盘一节
                       "## RAW JSONL STREAM",含 LLM 全部中间 assistant 消息 +
                       tool_use blocks,便于审计 LLM 是否真读了清单文件。
                       默认 None 等同 'text' 行为,保持向后兼容。
                       注意:cosight CLI 要求 stream-json 必须配 --verbose,代码内
                       已自动追加。

    返回：
        子 Agent 的清理后输出（提取了 markdown code fence 中的内容）；失败返回 ""

    观测性：
        每次调用都会把 system / user prompt、stdout、stderr、returncode、
        duration 等完整上下文落盘到 {SKILLX_CURRENT_TASK_DIR}/_debug/agent_*.txt
        （前提是该环境变量已被 orchestrator 设置）。
    """
    project_root = _find_agents_dir(Path(cwd) if cwd else None)
    debug_dir = _resolve_debug_dir()

    # 加载子 Agent 定义（支持占位符渲染）
    agent_def = ""
    load_error: Optional[str] = None
    try:
        agent_def = _load_agent_definition(subagent_type, project_root, context=context)
    except FileNotFoundError as e:
        load_error = str(e)
        print(f"  ⚠️ {e}")

    system_prompt = agent_def if agent_def else (
        "你是一个专业的分析助手。请根据用户指令完成分析任务，输出结构化结果。"
    )

    print(f"  [Agent] 调用子 Agent: {subagent_type} — {description}")
    if timeout is not None:
        print(f"  [Agent] 显式超时: {timeout}s")
    # 2026-07-21 根除:不再读 SKILLX_AGENT_TIMEOUT 环境变量
    if settings_path:
        print(f"  [Agent] 自定义 settings: {settings_path}")

    # 子 Agent 定义找不到 → 直接返回（保留原行为），但仍落盘以便审查
    if load_error:
        _dump_agent_call(
            debug_dir=debug_dir,
            subagent_type=subagent_type,
            description=description,
            system_prompt="",
            user_prompt=prompt,
            stdout="",
            stderr="",
            returncode=None,
            duration_sec=0.0,
            timeout=timeout,
            settings_path=settings_path,
            exception=f"FileNotFoundError: {load_error}",
        )
        return ""

    # 调用 claude -p
    stdout, stderr, returncode, duration_sec, exception_str, raw_jsonl = _call_claude_pipe(
        system_prompt, prompt,
        timeout=timeout, settings_path=settings_path, output_format=output_format,
    )

    # 始终落盘（成功 / 失败都落，便于事后比对）
    dumped_path = _dump_agent_call(
        debug_dir=debug_dir,
        subagent_type=subagent_type,
        description=description,
        system_prompt=system_prompt,
        user_prompt=prompt,
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
        duration_sec=duration_sec,
        timeout=timeout,
        settings_path=settings_path,
        exception=exception_str,
        raw_jsonl=raw_jsonl,
    )
    if dumped_path is not None:
        print(f"  [Agent] 调用上下文落盘: {dumped_path}")

    # 失败分类：异常 / 非零退出码 / stderr 不为空
    if exception_str:
        print(f"  ⚠️ 子 Agent {subagent_type} 调用异常: {exception_str}")
        if stderr:
            print(f"  [stderr 预览]: {stderr[:300]}")
        return ""
    if returncode is not None and returncode != 0:
        print(f"  ⚠️ 子 Agent {subagent_type} 退出码 {returncode}")
        if stderr:
            print(f"  [stderr 预览]: {stderr[:300]}")
        return ""
    if stderr:
        # 成功但 stderr 不为空：仅当含警告/错误关键字时简短提示，不阻塞
        if re.search(r"(?i)\b(error|warning|warn|fail)\b", stderr):
            print(f"  [Agent] stderr 含告警(预览 200 字): {stderr[:200]}")

    # 🆕 2026-08-01 根治:多层 fence 抽取(原版单层 fence 抽取失败率 100%)
    # 实测 taskid_20260801_073320/0006:STDOUT 118 行,LLM 真输出 JSON 被 cosight CLI 的
    # stdout 日志([Router] Primary failed / [BashTool] call() invoked) 包围,旧 fence
    # 正则 `(.*?)` 非贪婪匹配错位 → 抽到空字符串 → score.json 0 字节。
    # 修复:3 层 fallback
    # 1) 找最后一个 ```json ... ``` 块(LLM 真输出在最后)
    # 2) 找最后一个 ```...``` 块(LLM 可能忘了写 json 标签)
    # 3) 顶层 JSON 抽取(strip 后从 { 开始到 } 结束)
    output = stdout.strip()
    # 🆕 2026-08-01 根治:先剔除 cosight CLI 控制台日志行([Transformer] / [BashTool] /
    # [Router] / [stdout-guard] / [Transformer] 等),它们污染 LLM 真输出导致 fence 抽错。
    # 验证:taskid_20260801_073320/0002(score-analyzer)STDOUT 103 行含 30 行 cosight 日志,
    # 之前 fence 抽取把这 30 行也算进去,导致 result_diff_report 出现 "RAN-4988439 失分诊断
    # 中间一段 [BashTool] call() invoked" 这种污染。
    output = re.sub(
        r'^\[(?:Transformer|stdout-guard|BashTool|ReadTool|GrepTool|GlobTool|EditTool|WriteTool|NotebookEdit|Router|User|System|Assistant)\][^\n]*\n',
        '',
        output,
        flags=re.MULTILINE,
    )
    output = output.strip()
    fence_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', output, re.DOTALL)
    if fence_match:
        output = fence_match.group(1).strip()
    else:
        # 退路 1:找最后一个 \`\`\`json 块(LLM 输出可能多 fence)
        last_json_idx = output.rfind("```json")
        if last_json_idx != -1:
            after_fence = output[last_json_idx:].lstrip("`").lstrip("json").lstrip()
            if after_fence.startswith("\n"):
                after_fence = after_fence[1:]
            close_idx = after_fence.rfind("```")
            if close_idx != -1:
                output = after_fence[:close_idx].rstrip("\n")
        # 退路 2:顶层 JSON 抽取(strip 后第一个 { 到 匹配的 })
        if not output.startswith("{"):
            start_idx = output.find("{")
            if start_idx != -1:
                depth = 0
                for j in range(start_idx, len(output)):
                    if output[j] == "{":
                        depth += 1
                    elif output[j] == "}":
                        depth -= 1
                        if depth == 0:
                            output = output[start_idx:j+1]
                            break

    return output


def _dump_llm_call(
    label: str,
    system_prompt: str,
    user_prompt: str,
    raw_response: str,
    parsed_result: Optional[str] = None,
    exception: Optional[str] = None,
    duration_sec: Optional[float] = None,
    http_status: Optional[int] = None,
    retries: int = 0,
) -> Optional[Path]:
    """把 HTTP 直调（call_llm_api / call_llm_json）的完整上下文写到 _debug 文件。

    格式与 _dump_agent_call 一致（system/user/raw response/parsed result 分节），
    文件名以 `agent_{label}_` 前缀，与 subagent 路径同目录便于全局对比排查。

    落盘失败只 warning，不阻断主链路。
    """
    debug_dir = _resolve_debug_dir()
    if debug_dir is None:
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    seq = _next_agent_call_seq()
    safe_label = re.sub(r"[^A-Za-z0-9_.-]", "_", label)[:40]
    fname = f"agent_{safe_label}_{timestamp}_{os.getpid()}_{seq:04d}.txt"
    target = debug_dir / fname

    try:
        with target.open("w", encoding="utf-8") as fp:
            fp.write(f"# label         : {label}\n")
            fp.write(f"# timestamp     : {datetime.now().isoformat()}\n")
            fp.write(f"# pid           : {os.getpid()}\n")
            fp.write(f"# seq           : {seq}\n")
            fp.write(f"# http_status   : {http_status}\n")
            fp.write(f"# retries       : {retries}\n")
            fp.write(f"# duration_sec  : {duration_sec:.2f}\n" if duration_sec is not None else "# duration_sec  : unknown\n")
            fp.write(f"# exception     : {exception or '(none)'}\n")
            fp.write("\n## SYSTEM PROMPT (begin)\n")
            fp.write(system_prompt or "")
            fp.write("\n## SYSTEM PROMPT (end)\n")
            fp.write("\n## USER PROMPT (begin)\n")
            fp.write(user_prompt or "")
            fp.write("\n## USER PROMPT (end)\n")
            fp.write("\n## RAW RESPONSE (begin)\n")
            fp.write(raw_response or "")
            fp.write("\n## RAW RESPONSE (end)\n")
            if parsed_result:
                fp.write("\n## PARSED RESULT (begin)\n")
                fp.write(parsed_result)
                fp.write("\n## PARSED RESULT (end)\n")
        return target
    except Exception as e:
        print(f"  ⚠️ [LLM] 调用日志落盘失败: {e}")
        return None
