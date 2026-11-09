"""static_evaluator_subprocess.py — 独立可执行的 evaluator 子进程入口。

⚠️ DEPRECATED（.18+，cosight → alpha 同步标注）

本文件 .12+ 走"Co-sight Pro 原生 agent_loop + urllib + Anthropic Messages + tool_use"协议，
**不依赖 cosight runtime（cc）/ tools.Agent**。

- 本文件曾在 cosight-agent-core/extensions/skillx-cosight 作为 .12+ 唯一路径；
- skillx-alpha-agents 是 **基于 cc 的 harness**（COSIGHT.md §1），主流程已不再调用本文件
  （仅 _resolve_subprocess_script 被 static_agents:228 静态引用，未实际 Popen）；
- alpha 实际使用 `static_agents.invoke_evaluator(score_mode="subagent")`，
  借 cc `tools.Agent` 调真子 Agent（cosight .17+ 路径，详见 static_agents.py）。

**仅在以下场景仍有用**：把本文件作为独立脚本脱机运行（不需要 cc runtime 的纯 Python 环境）。
代码保留为可选 adapter，不删除（避免破坏可能存在的离线评测 fixture）。

历史背景：
 B 方案：把 evaluator 拆成子进程,断绝主进程状态污染。
.12+ 架构：Co-sight Pro 原生 agent loop（不依赖 cosight / tools.Agent）
- 用 urllib + Anthropic Messages + tool_use 协议实现真子 agent
- 工具执行器（Read/Bash/Grep/Glob/Write）全部在 subprocess 本地用 Python 实现
- 循环直到 stop_reason="end_turn"，不构造固定 prompt
- 符合用户原则：永远子agent，不构造固定 prompt，不依赖 cc

为什么需要子进程:
- LLM judge 在主进程里多次调用会共享 HTTP 连接池、Python 解释器状态、模块缓存;
  跨轮 R1→R2→R3 看似独立,实际可能因 LLM API 端缓存或客户端 keep-alive 复用而"看到"前次结果
- 子进程是全新 Python 解释器,无任何 in-memory 状态(只有文件系统视角)
- 每次 evaluator 启动一次,销毁后不留任何运行痕迹

.12+ 模式（独立脱机运行，**非 alpha 主流程**）：
- SKILLX_EVAL_MODE=subagent (默认): 走 _run_subagent,用 agent_loop + tool_use
- SKILLX_EVAL_MODE=llm_call: 抛 RuntimeError（_run_llm_call 已废弃）

调用方式:
    python3 static_evaluator_subprocess.py \\
        --skill-root /path/to/skill \\
        --target-files "SKILL.md,scripts/foo.sh" \\
        --output-path /tmp/run_0.json \\
        --framework-cfg '{"rubric": {...}, ...}' \\
        --round-num 1 \\
        --nonce uuid-xxx

退出码:0 成功,1 失败。

alpha harness 调用方式（基于 cc）:
    # 静态优化器 alpha（.18+）默认走 llm_direct，subagent 模式由 CLI/env 切换：
    python3 scripts/orchestrator.py --mode static --score-mode subagent \\
        --skill-path /path/to/SKILL.md ...   # 走 static_agents.invoke_evaluator(score_mode='subagent')
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import re
import sys
import time
import traceback
from pathlib import Path

# 把 optimizers 父包加进 sys.path
_THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS_DIR.parent))

# 子进程独立日志(写到 stderr,主进程从 Popen.stderr 读)
logging.basicConfig(
    level=logging.INFO,
    format=f"[evaluator-sub pid={os.getpid()}] %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("static_evaluator_subprocess")


def _resolve_subprocess_script() -> Path:
    """返回本子进程脚本的绝对路径,供主进程 Popen 调用。

    主进程调 `subprocess.Popen([sys.executable, _resolve_subprocess_script(), ...])`
    """
    return Path(__file__).resolve()


# .12+：native agent_loop 的独立审计日志（不依赖 tools.py 的 _dump_agent_call）
# subprocess 不能 import tools（依赖 Co-sight Pro runtime），所以本地实现一份。
def _dump_agent_call(
    debug_dir: Optional[Path],
    subagent_type: str,
    description: str,
    system_prompt: str,
    user_prompt: str,
    messages_trajectory: list[dict],
    final_text: str,
    duration_sec: float,
    exception: Optional[str] = None,
) -> Optional[Path]:
    """把 native agent_loop 的完整调用上下文写到 _debug 文件。

    文件名格式：agent_{type}_{timestamp}_{pid}_{seq}.txt（与 tools.Agent 一致）
    """
    if debug_dir is None:
        return None
    debug_dir = Path(debug_dir)
    if not debug_dir.exists():
        try:
            debug_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return None

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_type = re.sub(r"[^A-Za-z0-9_.-]", "_", subagent_type)[:40]
    # 用 microseconds 保证唯一
    seq = int(datetime.datetime.now().microsecond / 1000) % 10000
    fname = f"agent_{safe_type}_{timestamp}_{os.getpid()}_{seq:04d}.txt"
    target = debug_dir / fname

    try:
        with target.open("w", encoding="utf-8") as fp:
            fp.write(f"# subagent_type : {subagent_type}\n")
            fp.write(f"# description   : {description}\n")
            fp.write(f"# timestamp     : {datetime.datetime.now().isoformat()}\n")
            fp.write(f"# pid           : {os.getpid()}\n")
            fp.write(f"# seq           : {seq}\n")
            fp.write(f"# duration_sec  : {duration_sec:.2f}\n")
            fp.write("# mode          : Co-sight Pro native agent_loop (urllib + Anthropic tool_use)\n")
            fp.write(f"# exception     : {exception or '(none)'}\n")
            fp.write("\n## SYSTEM PROMPT (begin)\n")
            fp.write(system_prompt or "")
            fp.write("\n## SYSTEM PROMPT (end)\n")
            fp.write("\n## USER PROMPT (begin)\n")
            fp.write(user_prompt or "")
            fp.write("\n## USER PROMPT (end)\n")

            # 完整 messages 轨迹（含 tool_use + tool_result）
            fp.write("\n## Messages Trajectory (begin)\n")
            for i, msg in enumerate(messages_trajectory):
                fp.write(f"\n--- message[{i}] role={msg.get('role', '?')} ---\n")
                content = msg.get("content")
                if isinstance(content, str):
                    fp.write(content)
                elif isinstance(content, list):
                    for blk in content:
                        btype = blk.get("type", "?")
                        if btype == "text":
                            fp.write(f"[text] {blk.get('text', '')}\n")
                        elif btype == "tool_use":
                            fp.write(f"[tool_use] {blk.get('name', '?')}("
                                     f"{json.dumps(blk.get('input', {}), ensure_ascii=False)[:500]})\n")
                        elif btype == "tool_result":
                            content_val = blk.get('content', '')
                            if isinstance(content_val, list):
                                content_str = json.dumps(content_val, ensure_ascii=False)
                            else:
                                content_str = str(content_val)
                            fp.write(f"[tool_result] {content_str[:2000]}\n")
                        else:
                            fp.write(f"[{btype}] {json.dumps(blk, ensure_ascii=False)[:500]}\n")
            fp.write("\n## Messages Trajectory (end)\n")

            fp.write("\n## FINAL TEXT (begin)\n")
            fp.write(final_text or "")
            fp.write("\n## FINAL TEXT (end)\n")
        return target
    except Exception as e:
        logger.warning("agent_*.txt 审计日志落盘失败: %s", e)
        return None


def _eval_mode() -> str:
    """返回 SKILLX_EVAL_MODE，默认 subagent。

    .12+：永远走 Co-sight Pro 原生 sub-agent（_run_llm_call 已废弃）。
    设 SKILLX_EVAL_MODE=llm_call 会抛 RuntimeError 拒绝旧路径。
    """
    return os.environ.get("SKILLX_EVAL_MODE", "subagent").strip().lower()


def _render_rubric_section(rubric: dict) -> str:
    """将 YAML rubric 渲染为 Markdown 表格 + 详细 criteria 段落。

    Args:
        rubric: framework_configs/static-eval-config.yaml 的 rubric 段

    Returns:
        渲染后的 Markdown 文本
    """
    lines = []
    # 表格头
    lines.append("| # | 维度 | 权重 | 杠杆点 | 评分要点（摘要） |")
    lines.append("|---|------|------|--------|-----------------|")

    # 收集维度信息
    dim_info = []
    for idx, (key, cfg) in enumerate(rubric.items(), 1):
        if not key.startswith("dim"):
            continue
        name = cfg.get("name", key)
        weight = cfg.get("weight", 1.0)
        leverage_note = cfg.get("leverage_note", "—")
        criteria = cfg.get("criteria", "")
        # 取 criteria 第一行作为摘要
        summary = criteria.strip().split("\n")[0] if criteria else "—"
        dim_info.append((idx, name, weight, leverage_note, summary, criteria))

    # 生成表格
    for idx, name, weight, leverage, summary, _ in dim_info:
        lines.append(f"| {idx} | **{name}** | {weight} | {leverage} | {summary} |")

    lines.append("")
    lines.append("### 各维度详细 criteria")
    lines.append("")

    # 生成详细 criteria 段落
    for idx, name, weight, leverage, summary, criteria in dim_info:
        lines.append(f"#### dim{idx}: {name} (权重 {weight})")
        lines.append("")
        if leverage != "—":
            lines.append(f"**杠杆点**: {leverage}")
            lines.append("")
        lines.append("**评分标准**:")
        lines.append("```")
        lines.append(criteria.strip())
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def _make_tool_executor(
    skill_root: Path,
    exempt_paths: "Optional[set[Path]]" = None,
) -> "callable":
    """构造工具执行器：在 subprocess 本地执行 Read/Bash/Grep/Glob/Write。

    不依赖 cosight / Co-sight Pro runtime。
    Anthropic tool_use 协议要求每个 tool 返回字符串结果。

    Args:
        skill_root: Skill 根目录；越权检查的边界。
        exempt_paths: 这些绝对路径允许越界写入（仅用于 output_path 等主进程指定产物）。
            .x 修复：原版硬约束"Write 必须落在 skill_root 内"与 user_prompt 里
            "写 output_path（外层绝对路径）"设计性冲突，LLM 被拒后自救命名
            `backup_score_sub0_retry2.json` 等写进 skill_root，污染 worktree→best_skill。
            现在加白名单——主进程把 `output_path` 传进来，Write 工具对白名单内路径放行。
    """
    import subprocess as _sp

    if exempt_paths is None:
        exempt_paths = set()
    exempt_resolved: set[Path] = set()
    for p in exempt_paths:
        if p is None:
            continue
        try:
            exempt_resolved.add(Path(p).resolve())
        except (OSError, RuntimeError):
            # resolve 失败（路径不存在 / 权限问题）也允许 unlink 时再判断
            exempt_resolved.add(Path(p))

    def _resolve(path: str) -> tuple[Optional[Path], Optional[str]]:
        """路径安全解析：限制在 skill_root 内（防 ../ 越狱）。

        .x 修复：在越权检查前先看 exempt_paths 白名单。
        """
        p = Path(path)
        if not p.is_absolute():
            p = (skill_root / p).resolve()
        else:
            p = p.resolve()
        # 豁免白名单（output_path 等主进程指定产物）— 跳过越权检查
        if exempt_resolved and p in exempt_resolved:
            return p, None
        # 也检查 basename 匹配（LLM 可能传相对路径如 "score.sub0.json"）
        for ex_p in exempt_resolved:
            if p.name == ex_p.name:
                return p, None
        # 越权检查
        try:
            p.relative_to(skill_root.resolve())
        except ValueError:
            return None, f"路径越界: {path}（必须位于 {skill_root} 内）"
        return p, None

    def _exec(tool_name: str, tool_input: dict) -> str:
        try:
            if tool_name == "Read":
                path_str = tool_input.get("file_path", "")
                p, err = _resolve(path_str)
                if err:
                    return err
                if not p.exists():
                    return f"文件不存在: {path_str}"
                limit = int(tool_input.get("limit", 2000))
                offset = int(tool_input.get("offset", 0))
                text = p.read_text(encoding="utf-8", errors="replace")
                lines = text.splitlines()
                start = offset
                end = offset + limit
                chunk = "\n".join(f"{i+1:4d}| {ln}" for i, ln in enumerate(lines[start:end], start=start))
                return chunk or "(空文件)"

            elif tool_name == "Glob":
                pattern = tool_input.get("pattern", "**/*")
                paths = sorted(skill_root.glob(pattern))
                # 只列文件，过滤二进制
                result = []
                for p in paths[:200]:
                    if p.is_file():
                        try:
                            rel = p.relative_to(skill_root)
                            result.append(f"{rel}\t{p.stat().st_size}B")
                        except ValueError:
                            pass
                return "\n".join(result) if result else "(无匹配)"

            elif tool_name == "Grep":
                pattern = tool_input.get("pattern", "")
                path = tool_input.get("path", ".")
                glob = tool_input.get("glob", "**/*")
                if not pattern:
                    return "Grep pattern 不能为空"
                p, err = _resolve(path)
                if err:
                    return err
                # 用 ripgrep / grep 不可控,这里用 python 实现
                import re as _re
                search_root = p if p.is_dir() else p.parent
                rx = _re.compile(pattern)
                hits = []
                for f in search_root.rglob("*"):
                    if not f.is_file():
                        continue
                    try:
                        text = f.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        continue
                    for i, ln in enumerate(text.splitlines(), 1):
                        if rx.search(ln):
                            try:
                                rel = f.relative_to(skill_root)
                            except ValueError:
                                rel = f
                            hits.append(f"{rel}:{i}: {ln[:200]}")
                            if len(hits) >= 200:
                                hits.append("...(截断,200 行)")
                                break
                    if len(hits) >= 200:
                        break
                return "\n".join(hits) if hits else "(无匹配)"

            elif tool_name == "Bash":
                cmd = tool_input.get("cmd", "")
                timeout = int(tool_input.get("timeout", 30))
                if not cmd:
                    return "Bash cmd 不能为空"
                # 安全限制：禁止 rm -rf / / dd / mkfs / shutdown 等危险命令
                dangerous = ["rm -rf /", "dd if=", "mkfs", "shutdown", "reboot", ":(){:|:&};:"]
                for d in dangerous:
                    if d in cmd:
                        return f"危险命令被拦截: {cmd!r} 含 {d!r}"
                try:
                    r = _sp.run(
                        cmd, shell=True, cwd=str(skill_root),
                        capture_output=True, text=True, timeout=timeout,
                    )
                    out = (r.stdout or "")[:5000]
                    err = (r.stderr or "")[:2000]
                    return f"exit_code={r.returncode}\nstdout:\n{out}\nstderr:\n{err}".strip()
                except _sp.TimeoutExpired:
                    return f"Bash 超时（>{timeout}s）: {cmd}"
                except Exception as e:
                    return f"Bash 异常: {type(e).__name__}: {e}"

            elif tool_name == "Write":
                file_path = tool_input.get("file_path", "")
                content = tool_input.get("content", "")
                p, err = _resolve(file_path)
                if err:
                    return err
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
                return f"已写入 {p}（{len(content)} 字符）"

            else:
                return f"未知 tool: {tool_name}"
        except Exception as e:
            return f"tool {tool_name} 执行异常: {type(e).__name__}: {e}"

    return _exec


def _build_skill_evaluator_tools_schema() -> list[dict]:
    """Anthropic tool_use 协议：声明 sub-agent 可用的工具集。"""
    return [
        {
            "name": "Read",
            "description": "读取 skill 文件内容（带行号），用于看 SKILL.md / scripts / references。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "相对 skill_root 的文件路径或绝对路径"},
                    "limit": {"type": "integer", "description": "最多读多少行（默认 2000）", "default": 2000},
                    "offset": {"type": "integer", "description": "从第几行开始（默认 0）", "default": 0},
                },
                "required": ["file_path"],
            },
        },
        {
            "name": "Glob",
            "description": "按 glob 模式列文件（如 '**/*.md' 或 'references/*.py'），用于发现 skill 结构。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "glob 模式，相对于 skill_root", "default": "**/*"},
                },
                "required": [],
            },
        },
        {
            "name": "Grep",
            "description": "在 skill 目录按正则搜索关键词定位行号，用于 dim 评分的 evidence 收集。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "正则表达式（Python re 语法）"},
                    "path": {"type": "string", "description": "搜索根目录（相对 skill_root），默认 .", "default": "."},
                    "glob": {"type": "string", "description": "文件类型过滤（如 **/*.md）", "default": "**/*"},
                },
                "required": ["pattern"],
            },
        },
        {
            "name": "Bash",
            "description": "执行 shell 命令（如 ls / find / wc -l），用于辅助信息收集。危险命令会被拦截。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "shell 命令"},
                    "timeout": {"type": "integer", "description": "超时秒数（默认 30）", "default": 30},
                },
                "required": ["cmd"],
            },
        },
        {
            "name": "Write",
            "description": "写文件（output_path 等白名单路径放行，非白名单路径必须位于 skill_root 内），用于最终写出 score.json。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "目标文件路径（绝对路径或相对路径；output_path 已加入白名单放行）"},
                    "content": {"type": "string", "description": "要写入的完整内容"},
                },
                "required": ["file_path", "content"],
            },
        },
    ]


def _run_subagent(
    skill_root: Path,
    target_files: list[Path],
    output_path: Path,
    framework_cfg: dict,
    args,
) -> int:
    """.12+ 唯一路径：用 Co-sight Pro 原生 agent_loop 跑 skill-evaluator 真子 agent。

    不调 tools.Agent()（与 cosight 无关）、不调 _run_llm_call（不构造固定 prompt）。
    用 urllib + Anthropic Messages + tool_use 协议实现 agent loop：

    - system prompt 从 agents/skill-evaluator-agent.md 读取（带占位符渲染）
    - 工具执行器：Read/Bash/Grep/Glob/Write 全部在 subprocess 本地用 Python 实现
    - 循环：LLM 自主决定调哪个 tool → 主进程执行 → 返回 tool_result → 直到 stop_reason="end_turn"
    - sub-agent 用 Write 工具把 score.json 写到 output_path
    - 主进程二次调 _recompute_total_and_validate 防 LLM 自填 total bug

    .12+ 行为：
    - sub-agent 自主 Read SKILL.md → Glob 看结构 → Grep 找 evidence
    - sub-agent 决定读哪些附属文件（不再固定 ≤10 个,不再模板拼接塞全文）
    - dim_score 写 score.json 后,主进程仍调 _recompute_total_and_validate 二次校验
    """
    from optimizers.static_llm import LLMConfig, agent_loop

    # 1. 加载 agent definition（支持占位符渲染）
    project_root = Path(__file__).resolve().parents[2]
    agent_def_path = project_root / "." / "agents" / "skill-evaluator-agent.md"
    if not agent_def_path.exists():
        raise FileNotFoundError(f"agent definition 不存在: {agent_def_path}")
    system_prompt = agent_def_path.read_text(encoding="utf-8")

    # 2. 渲染占位符（v3：只渲染 rubric；anti_patterns 已融进 dim 的 anti_criteria 段）
    rubric = framework_cfg.get("rubric", {})
    system_prompt = system_prompt.replace(
        "{{RUBRIC_SECTION}}", _render_rubric_section(rubric)
    )

    # 3. 构造 user prompt（只给关键参数，不塞全文——让 LLM 自主 Read）
    target_files_rel = [str(f.relative_to(skill_root)) for f in target_files if f.exists()]
    rubric_dims = sorted(k for k in rubric.keys() if k.startswith("dim"))

    user_prompt = f"""请对以下 skill 做静态评估。详细评分标准已在 system prompt 中（rubric criteria + 反例黑名单）。

## 输入
- skill_root: {skill_root}
- target_files（框架传入的初始列表，可选读）: {target_files_rel}
- output_path（最终写产物到这里）: {output_path}
- round_num: {args.round_num}
- nonce: {args.nonce}
- expert_guidance: {args.expert_guidance or '(无)'}
- 已启用 dim: {rubric_dims}（共 {len(rubric_dims)} 维）

## 4 阶段方法论
1. Phase 1（发现）：Glob skill_root 看结构 → Read SKILL.md 全文 → Read framework YAML（如果需要）
2. Phase 2（证据收集）：每 dim Grep+Read 找具体证据（文件:行号 + 原文片段）
3. Phase 3（交叉验证）：对 low_score dim 二次 Read 确认
4. **🔴 Phase 4（写产物）**：用 `Write` 工具写 `{output_path}`。
   - JSON 字段: round / total / rating / dim_scores / gaps / anti_pattern_hits / expert_guidance_ref / scored_at
   - dim_scores 全部 ∈ [0, 10]（整数或 1 位小数），否则 score.json 会被主进程拒收
   - 推荐额外含 evidence 字段（每 dim 文件:行号 + snippet）便于审计

**🔴 死线约束**：评分完成后**必须**用 `Write` 工具写 `{output_path}`。Write 白名单已放行此路径。stdout 输出 Markdown 表格 → FileNotFoundError → REWORK。不要用 `print()` 替代 `Write`。
"""

    logger.info(
        "evaluator (subagent/native_loop) 启动: skill_root=%s, nonce=%s",
        skill_root, args.nonce[:8] if args.nonce else "(none)",
    )

    # 4. 构造 tool_executor 和 tools schema
    # .x 修复：把 output_path 加入豁免白名单，让 sub-agent 第一次 Write 就写对位置
    # 否则 LLM 被 _resolve 拒收后会自救命名 backup_score_*.json 等写进 skill_root，污染 worktree
    tool_executor = _make_tool_executor(skill_root, exempt_paths={output_path})
    tools_schema = _build_skill_evaluator_tools_schema()

    # 5. 调 LLMConfig
    llm_cfg = LLMConfig.from_yaml(
        project_root / "config" / "optimize-user-config.yaml"
    ).with_env_override()

    # 6. 跑 native agent loop（不依赖 cosight）
    loop_start = time.monotonic()
    final_text, messages_trajectory = agent_loop(
        system=system_prompt,
        user_prompt=user_prompt,
        tools_schema=tools_schema,
        tool_executor=tool_executor,
        config=llm_cfg,
        max_iterations=30,
        max_tokens_per_call=8192,
        nonce=args.nonce,
        verbose=True,
    )
    loop_duration = time.monotonic() - loop_start

    # .12+：native agent_loop 审计日志 — 写到 _debug/agent_*.txt（与 tools.Agent 格式对齐）
    # 路径策略：优先 SKILLX_CURRENT_TASK_DIR（orchestrator 设置），否则用 score.json 同目录的 _debug
    debug_dir = None
    task_dir_env = os.environ.get("SKILLX_CURRENT_TASK_DIR", "").strip()
    if task_dir_env:
        debug_dir = Path(task_dir_env) / "_debug"
    else:
        debug_dir = output_path.parent.parent / "_debug"
    _dump_agent_call(
        debug_dir=debug_dir,
        subagent_type="skill-evaluator",
        description=f"skill-evaluator (round={args.round_num}, nonce={args.nonce[:8]})",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        messages_trajectory=messages_trajectory,
        final_text=final_text,
        duration_sec=loop_duration,
    )

    # 7. 校验 score.json 产出
    if not output_path.exists():
        # 兜底：agent 没 Write 文件但 final_text 非空 → 尝试提取 JSON
        result = None
        if final_text and final_text.strip():
            # 7a. 尝试从 final_text 解析 JSON
            maybe_json = final_text.strip()
            # 去掉 markdown 代码围栏（如果有）
            if maybe_json.startswith("```"):
                maybe_json = maybe_json.split("```", 2)[-2] if "```" in maybe_json[3:] else maybe_json
                maybe_json = maybe_json.strip()
            if maybe_json.startswith("{"):
                try:
                    result = json.loads(maybe_json)
                except json.JSONDecodeError:
                    pass
        if result is None:
            # 7b. 非 JSON 输出 → 尝试从 Markdown 表格提取 dim_scores
            dim_scores_fallback: dict[str, float] = {}
            import re as _re_tbl
            for line in final_text.split(chr(10)):
                # 匹配 Markdown 表格行: | dim1_frontmatter | 8 | ...
                m = _re_tbl.search(r"\|\s*(\w+)\s*\|\s*(\d+)\s*\|", line)
                if m:
                    dim_key = m.group(1)
                    score_val = float(m.group(2))
                    if dim_key.startswith("dim") or any(
                        dim_key.startswith(p) for p in ["dim", "dim1_", "dim2_", "dim3_", "dim4_", "dim5_", "dim6_", "dim7_", "dim8_", "dim9_", "dim10_", "dim11_", "dim12_"]
                    ):
                        dim_scores_fallback[dim_key] = min(max(score_val / 10.0, 0.0), 1.0) * 10 if score_val > 10 else min(max(score_val, 0.0), 10.0)
            fallback_total = sum(dim_scores_fallback.values()) / max(len(dim_scores_fallback), 1) * 10 if dim_scores_fallback else 0.0
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps({
                    "round": args.round_num,
                    "total": round(fallback_total, 2),
                    "rating": "FAIR" if dim_scores_fallback else "BROKEN",
                    "dim_scores": dim_scores_fallback,
                    "gaps": [f"sub-agent 未输出 JSON, final_text 前 300 字符: {final_text[:300]!r}"],
                    "anti_pattern_hits": [],
                    "expert_guidance_ref": "",
                    "_evidence_raw": final_text[:3000],
                    "_error": "sub-agent 未输出 JSON" if not dim_scores_fallback else "",
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if dim_scores_fallback:
                logger.info("从 Markdown 表格提取 %d 维分数, total=%.2f", len(dim_scores_fallback), fallback_total)
                result = json.loads(output_path.read_text(encoding="utf-8"))
            else:
                # 根治：保留 score.json 写入（line 615-620）—— 不被外层 except 的 err_payload 覆盖
                # 改为 return 而非 raise：让 main 正常结束（sub-agent 失败 → 0 分 + _error 标记）
                # 主流程拿 0 分不触发 REWORK（避免反复重试同一个失败的 sub-agent）
                logger.warning("sub-agent 未输出 JSON, 已写入 %s (return 0 分, 不触发 REWORK)", output_path)
                return
        # 写到 output_path 供后续流程使用
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("从 final_text 提取 JSON 写入 %s", output_path)
    else:
        result = json.loads(output_path.read_text(encoding="utf-8"))
    if result.get("_error"):
        raise RuntimeError(f"sub-agent 返回 error: {result['_error'][:200]}")

    # 8. .11+: 主进程二次校验 sub-agent 写的 score.json
    dim_scores = result.get("dim_scores", {}) or {}
    from optimizers.static_agents import _recompute_total_and_validate
    result["total"], result["rating"] = _recompute_total_and_validate(
        dim_scores, framework_cfg,
    )

    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(
        "evaluator (subagent/native_loop) 完成: total=%s, output=%s",
        result.get("total"), output_path,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="/skill_optimize evaluator 子进程入口")
    parser.add_argument("--skill-root", required=True, help="Skill 根目录")
    parser.add_argument(
        "--target-files", default="SKILL.md",
        help="要评估的文件列表,逗号分隔,相对 skill_root",
    )
    parser.add_argument("--output-path", required=True, help="评分结果 JSON 输出路径")
    parser.add_argument(
        "--framework-cfg", default="{}",
        help="framework YAML 解析结果(JSON 字符串)",
    )
    parser.add_argument("--round-num", type=int, default=1)
    parser.add_argument("--nonce", default="", help="唯一标识(防 LLM API 端缓存)")
    parser.add_argument(
        "--expert-guidance", default="",
        help="用户自然语言指引",
    )
    args = parser.parse_args()

    try:
        skill_root = Path(args.skill_root).resolve()
        if not skill_root.is_dir():
            raise FileNotFoundError(f"skill_root 不存在: {skill_root}")

        target_files = [skill_root / f.strip() for f in args.target_files.split(",") if f.strip()]
        target_files = [f for f in target_files if f.exists()]
        if not target_files:
            raise FileNotFoundError(f"target_files 全部不存在: {args.target_files}")

        output_path = Path(args.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        framework_cfg = json.loads(args.framework_cfg) if args.framework_cfg else {}

        logger.info(
            "evaluator 子进程启动: skill_root=%s, target=%d 文件, nonce=%s",
            skill_root, len(target_files), args.nonce or "(none)",
        )

        # .12+：唯一路径——Co-sight Pro 原生 agent loop（不依赖 cosight）
        return _run_subagent(
            skill_root, target_files, output_path, framework_cfg, args,
        )

    except Exception as e:
        err_payload = {
            "round": args.round_num,
            "total": 0.0,
            "rating": "UNSCORED",
            "dim_scores": {},
            "gaps": [],
            "anti_pattern_hits": [],
            "expert_guidance_ref": "",
            "_error": str(e),
            "_traceback": traceback.format_exc()[-2000:],
        }
        try:
            Path(args.output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output_path).write_text(
                json.dumps(err_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass
        logger.error("evaluator 子进程失败: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
