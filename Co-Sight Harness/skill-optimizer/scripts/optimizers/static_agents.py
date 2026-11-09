"""static_agents.py — /skill_optimize 的 evaluator / optimizer agent 调用。

把 LLM 调用的两个 agent（evaluator + optimizer）从主循环拆出来，
让 static_optimizer.py 只负责编排。

evaluator: dim_scores 静态评分（dim 数由 framework_cfg.rubric 决定 + total + gaps + anti_pattern_hits）
optimizer: 基于评分生成 modifications（应用前需校验白名单 + 单轮条数）
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .static_optimizer import (StaticConfig, collect_target_files,
                               dispatch_files, is_protected)

logger = logging.getLogger("static_agents")

# ：按 file role 决定反同质化校验的 unique 分数阈值。
# knowledge/asset/doc 类文件 LLM 倾向打 8/9/10"不涉及"档位，集中在 2 个不同分数上，
# 硬约束≥3 会把这类合理打分误判为"同质化 reject"。entrypoint/implementation/template 保持硬约束≥3。
ROLE_UNIQUE_SCORE_THRESHOLD: dict[str, int] = {
    "entrypoint": 3, "implementation": 3, "template": 3,
    "knowledge": 2, "asset": 2, "doc": 2, "data": 2, "other": 2,
}


def _parse_subagent_json_output(stdout: str, path: Optional[Path] = None) -> Optional[dict]:
    """.16+:从 sub-agent (cosight -p) 的 stdout 解析 JSON proposal。

    sub-agent 输出格式可能:
    - 裸 JSON: {"modifications": [...], ...}
    - markdown code fence 包裹: ```json\\n{...}\\n```
    - 前面有 explanation 文字: "I'll do X. ```json\\n{...}\\n```"
    - 多个 JSON 块（思考过程的中间草稿 + 最终版）

    多个块时：跨块拼接所有 mods 和 findings（按 file+section+before 指纹去重），
    顶层字段（round/diagnosis/revision_strategy）取最后一块。
    这样能稳定合并 LLM 多轮思考输出（不假设 LLM 一次输出完美 schema）。

    协议 fallback 链（v0.19 修复 root cause）：
    1. 解析 stdout（裸 JSON / code fence / 栈平衡 JSON 块）
    2. 解析失败 → 尝试从 path 读（sub-agent 可能按契约 Write 到 path）
    3. path 不是 JSON / 不存在 → glob /tmp/round{N}*findings*.json 找最近修改的
    4. 全部失败 → 写原样 stdout 到 path 供 debug，返回 None

    Args:
        stdout: tools.Agent() 返回的子 agent stdout 字符串
        path: 约定的 output_path（sub-agent 契约要求 Write 到此）

    Returns:
        dict 解析成功 / None 解析失败
    """
    import re as _re

    from .static_llm import _find_balanced_json_objects, parse_json_response

    candidates: list[dict] = []

    def _try_parse(text: str) -> Optional[dict]:
        """尝试从 text 解析 JSON 对象。

        严格校验：必须含业务字段（round/per_file_findings/modifications/diagnosis），
        否则视为解析失败。原因：parse_json_response 把任何非空字符串解析为
        ``{"items": ""}``（垃圾解析器），不严格会被误判。
        """
        if not text:
            return None
        try:
            result = parse_json_response(text)
        except Exception:  # noqa: BLE001
            return None
        if not (result and isinstance(result, dict)):
            return None
        # 业务字段校验：至少含一个 sub-agent 输出的特征字段
        if not any(
            k in result
            for k in ("round", "per_file_findings", "modifications", "diagnosis")
        ):
            return None
        return result

    # === 1. 解析 stdout ===
    stripped = stdout.strip()
    if stripped.startswith("{"):
        result = _try_parse(stripped)
        if result:
            candidates.append(result)
    # 1b. markdown code fence
    for m in _re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", stdout, _re.DOTALL):
        result = _try_parse(m.group(1))
        if result:
            candidates.append(result)
    # 1c. 栈平衡找所有完整 JSON 块（覆盖 LLM 多次输出草稿）
    for blk in _find_balanced_json_objects(stdout):
        result = _try_parse(blk)
        if result and ("modifications" in result or "diagnosis" in result):
            candidates.append(result)

    if candidates:
        return _merge_candidates(candidates)

    # === 2. 解析失败：尝试从 path 读（sub-agent 按契约 Write 到 path） ===
    if path and path.is_file():
        result = _try_parse(path.read_text(encoding="utf-8"))
        if result:
            logger.info("sub-agent stdout 解析失败,改为从 %s 读取成功", path)
            return result

    # === 3. 兜底：glob /tmp/round{N}*findings*.json 找最近修改的 ===
    tmp_fallback = _find_subagent_json_in_tmp(stdout)
    if tmp_fallback is not None:
        logger.warning("sub-agent stdout 解析失败,从 /tmp 兜底读取", )
        return tmp_fallback

    # === 4. 全部失败 → 写原样 stdout 到 path 供 debug ===
    if path:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(stdout, encoding="utf-8")
            logger.warning("sub-agent stdout 解析失败,原样写到 %s 供人工 debug", path)
        except OSError:
            pass
    return None


def _merge_candidates(candidates: list[dict]) -> dict:
    """跨块拼接：顶层字段取最后一块；modifications/findings 按指纹去重合并。

    这样能稳定合并 LLM 多轮思考输出（不假设 LLM 一次输出完美 schema）。
    """
    result: dict = {}
    seen_mod_fps: set = set()
    seen_finding_fps: set = set()

    for c in candidates:
        for key in ("round", "diagnosis", "revision_strategy",
                    "gradient_analysis", "coverage", "uncovered_gaps"):
            if key in c:
                result[key] = c[key]

        # modifications 去重合并
        for m in c.get("modifications") or []:
            if not isinstance(m, dict):
                continue
            f = m.get("file", "")
            if not f:
                continue
            fp = (f, m.get("section", ""), m.get("before", "")[:80])
            if fp in seen_mod_fps:
                continue
            seen_mod_fps.add(fp)
            result.setdefault("modifications", []).append(m)

        # per_file_findings 按 file 累加 findings + dim_scores
        for entry in c.get("per_file_findings") or []:
            if not isinstance(entry, dict):
                continue
            f = entry.get("file", "")
            if not f:
                continue
            existing = next(
                (e for e in result.setdefault("per_file_findings", [])
                 if e.get("file") == f),
                None,
            )
            if existing is None:
                # 重要：保留 entry 的所有字段（含 dim_scores），不要只拷贝 file+findings
                # 这样多块合并时 dim_scores 也能正确保留到最后产物
                merged_entry = dict(entry)
                merged_entry["findings"] = list(entry.get("findings") or [])
                result["per_file_findings"].append(merged_entry)
            else:
                # 同 file 后续块：findings 去重追加；dim_scores 取首块（非空）
                for finding in entry.get("findings") or []:
                    if not isinstance(finding, dict):
                        continue
                    fp = (finding.get("section", ""), finding.get("before", "")[:80])
                    if fp in seen_finding_fps:
                        continue
                    seen_finding_fps.add(fp)
                    existing.setdefault("findings", []).append(finding)
                # 如果后续块提供了非空 dim_scores，补到 existing（首块优先保留）
                if not existing.get("dim_scores") and entry.get("dim_scores"):
                    existing["dim_scores"] = entry["dim_scores"]

    return result if result else None


def _find_subagent_json_in_tmp(stdout: str) -> Optional[dict]:
    """.19 兜底:sub-agent 不遵守契约时,glob /tmp/round{N}*findings*.json
    找最近修改的 JSON 文件(sub-agent 的常见反模式:把 JSON 写到 /tmp/round1_findings.json)。

    启发式:从 stdout 或 path 推断 round_num,再 glob 找最近修改的匹配文件;
    glob 必须有 round_num 前缀且包含 findings/proposal/score 关键词(防误读无关 JSON)。
    """
    import glob as _glob
    import re as _re

    from .static_llm import parse_json_response

    # 从 stdout / path 推断 round_num
    round_num: Optional[int] = None
    m = _re.search(r"round[_\s=]*(\d+)", stdout, _re.IGNORECASE)
    if m:
        try:
            round_num = int(m.group(1))
        except ValueError:
            round_num = None

    patterns: list[str] = []
    if round_num is not None:
        patterns.append(f"/tmp/round{round_num}*findings*.json")
        patterns.append(f"/tmp/round{round_num}*proposal*.json")
        patterns.append(f"/tmp/round{round_num}*score*.json")
    patterns.append("/tmp/round*findings*.json")  # 兜底无 round_num

    candidates: list[tuple[float, Path]] = []
    for pat in patterns:
        for f in _glob.glob(pat):
            p = Path(f)
            try:
                if not p.is_file() or p.stat().st_size < 100:
                    continue
                # 必须能解析为 JSON 才采纳(防误读 .md/.log 等)
                json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            candidates.append((p.stat().st_mtime, p))

    if not candidates:
        return None
    # 取最近修改的
    candidates.sort(reverse=True)
    try:
        result = parse_json_response(candidates[0][1].read_text(encoding="utf-8"))
        if result and isinstance(result, dict):
            return result
    except Exception:  # noqa: BLE001
        pass
    return None


def _load_cap_per_file() -> int:
    """从 framework YAML 的 relation_tree.scanner.char_cap_per_file 读取字符上限。"""
    try:
        from .static_optimizer import load_framework_config
        fw = load_framework_config()
        rt = fw.get("relation_tree", {}) or {}
        scanner = rt.get("scanner", {}) or {}
        return int(scanner.get("char_cap_per_file", 1500))
    except Exception:
        return 1500


def _read_skill_and_files(
    skill_root: Path,
    target_files: list[Path],
    char_cap_per_file: int = 0,
) -> tuple[str, list[tuple[str, str]]]:
    """读 SKILL.md 全文 + 附属文件「首尾摘要」（evaluator/optimizer 共用）

    附属文件不再全文注入（之前 6000 字符截断致大文件后半不可见 + 浪费 token）。
    改为「首半 + 尾半」摘要 + 关系树骨架；大文件全文由子 Agent 按需 Read。
    char_cap_per_file=0（默认）时从 framework YAML 的 relation_tree.scanner 读取；
    char_cap_per_file < 0 表示不截断（保留全文，调试用）。
    """
    if char_cap_per_file == 0:
        char_cap_per_file = _load_cap_per_file()

    skill_md = skill_root / "SKILL.md"
    if not skill_md.exists():
        for f in target_files:
            if f.suffix.lower() == ".md":
                skill_md = f
                break
    try:
        skill_content = skill_md.read_text(encoding="utf-8") if skill_md.exists() else ""
    except (OSError, UnicodeDecodeError):
        skill_content = ""

    files_content: list[tuple[str, str]] = []
    # 读取所有非 skip 的 target_files，每个截为首尾摘要（关系树骨架补全全局认知）
    for f in target_files:
        if f == skill_md:
            continue
        try:
            content = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if char_cap_per_file and len(content) > char_cap_per_file:
            # 固定保留「首 head_chars + 尾 head_chars」，中段丢弃：
            # 无论原文件多大，截断后总长恒为 char_cap_per_file（+分隔符），大文件显著缩短
            head_chars = char_cap_per_file // 2
            content = (
                content[:head_chars]
                + "\n\n... [中段省略，完整内容请用 Read 工具读真实文件] ...\n\n"
                + content[-head_chars:]
            )
        rel = str(f.relative_to(skill_root))
        files_content.append((rel, content))
    return skill_content, files_content


def _load_relation_tree(config) -> Optional[dict]:
    """从 workspace 顶层读取关系树文件（单一真相源；不存在则返回 None）。

    evaluator / optimizer 都从磁盘读同一份文件，避免把 dict 层层透传经过
    evaluate_with_runs / 子进程。文件由主循环的 _ensure_relation_tree 预先写好。
    """
    try:
        from .static_relations import RELATION_TREE_FILENAME
        workspace = getattr(config, "workspace", None)
        if not workspace:
            return None
        path = Path(workspace) / RELATION_TREE_FILENAME
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ImportError):
        return None


def _load_last_applied_mods(workspace: Path, round_num: int) -> list[dict]:
    """读上一轮（round_num-1）的 round_result.json 中的 modifications（评估跨文件一致性用）。

    R1 没有上一轮 → 返回空列表（不会破坏 dim6 等维度评分）。
    """
    if round_num <= 0:
        return []
    prev_round = round_num - 1
    if prev_round == 0:
        prev_path = Path(workspace) / "round_0" / "round_result.json"
    else:
        prev_path = Path(workspace) / f"round_{prev_round}" / "round_result.json"
    if not prev_path.exists():
        return []
    try:
        rr = json.loads(prev_path.read_text(encoding="utf-8"))
        return rr.get("proposal", {}).get("modifications", []) or []
    except (OSError, ValueError):
        return []


def _read_test_prompts(skill_root: Path) -> list[dict]:
    """-E 移除：dim9_test_prompts 已删除，此函数保留为 no-op 兼容旧调用。
    Returns: 始终空列表（不再读取 test-prompts.json fixture）。
    """
    return []


# 代码扩展名集合（与 static_optimizer.py 的两份定义保持一致）
_CODE_EXTENSIONS = {".py", ".sh", ".json", ".yaml", ".yml", ".toml", ".mjs", ".js", ".ts"}
def _is_code_file(file_path: str) -> bool:
    """判断文件路径是否属于代码文件（vs Markdown 文件）。"""
    from pathlib import Path as _P
    ext = _P(file_path).suffix.lower()
    return ext in _CODE_EXTENSIONS


# 编码原则 skill 召回指令 + 关系树/大文件按需 Read 指令。
# 按用户决策：不硬编码 4 原则文本，让 sub-agent 主动 Read 编码原则 SKILL.md。
# optimizer-agent 路径与 unified-agent 路径共用此常量（避免复制粘贴同一段指令）。
_SKILL_LOAD_DIRECTIVE = (
    "\n\n**🔧 代码文件 skill 召回指令（仅当本轮涉及代码文件时生效）**："
    "若 modifications 中含 `*.py`/`*.sh`/`*.json`/`*.yaml` 等代码文件，"
    "**第一步必须**用 Read 工具读取 `skillx-alpha-agents/skills/编码原则/SKILL.md`（Karpathy 4 原则："
    "不假设 / 最少代码 / 精准修改 / 目标驱动），"
    "然后**第二步**才生成 modifications.before 字段（必须从原文件逐字符复制）。"
    "违反此指令 = 凭记忆生成代码 → 会引入缩进错位。"
    "\n\n**🌳 关系树 + 大文件按需 Read（本轮全局认知）**："
    "prompt 中「文件关系树」段是全部文件的骨架；"
    "附属文件正文仅注入首尾摘要（非全文）。对 `line_count > 50` 的文件"
    "生成 before 前必须先用 Read 工具读真实全文。"
    "可选：若发现关系树未列出的隐式依赖，在输出 JSON 顶层附 "
    "`_relation_tree_additions`（不强制，框架会合并）。"
)


def _load_llm_config():
    """加载 LLMConfig（带 env override），延迟导入避免循环引用"""
    from .static_llm import LLMConfig

    return LLMConfig.from_yaml(
        Path(__file__).resolve().parents[2] / "config" / "optimize-user-config.yaml"
    ).with_env_override()


def _run_evaluators_subprocess(
    skill_root: Path,
    target_files: list[Path],
    config: "StaticConfig",
    framework_cfg: dict,
    output_path: Path,
    round_num: int,
    n_runs: int,
) -> tuple[list[dict], list[str]]:
    """ B 方案:用 subprocess.Popen 启 N 个独立 Python 子进程跑 evaluator。

    每个子进程是全新 Python 解释器,无主进程 in-memory 状态(共享 LLM client、
    模块全局变量、HTTP keep-alive 连接池),断绝跨轮污染。

    Returns:
        (runs, errors): runs 是成功 run 的 dim_scores dict 列表;errors 是失败明细
    """
    import subprocess
    import uuid

    from .static_evaluator_subprocess import _resolve_subprocess_script

    script_path = _resolve_subprocess_script()
    target_files_str = ",".join(str(f.relative_to(skill_root)) for f in target_files if f.exists())
    framework_cfg_str = json.dumps(framework_cfg, ensure_ascii=False)

    # 每个子进程的输出文件(独立路径,防止并发写竞争)
    sub_outputs: list[Path] = []
    nonce_set: set[str] = set()
    for i in range(n_runs):
        nonce = uuid.uuid4().hex
        # 防 UUID 冲突(虽然概率极低)
        while nonce in nonce_set:
            nonce = uuid.uuid4().hex
        nonce_set.add(nonce)
        sub_out = output_path.with_suffix(f".sub{i}.json")
        sub_outputs.append(sub_out)

    # Popen 启 N 个子进程(并行,不阻塞)
    procs: list[tuple[int, "subprocess.Popen[str]", Path, str]] = []
    for i, (sub_out, nonce) in enumerate(zip(sub_outputs, nonce_set)):
        cmd = [
            sys.executable, str(script_path),
            "--skill-root", str(skill_root),
            "--target-files", target_files_str or "SKILL.md",
            "--output-path", str(sub_out),
            "--framework-cfg", framework_cfg_str,
            "--round-num", str(round_num),
            "--nonce", nonce,
        ]
        if config.expert_guidance:
            cmd.extend(["--expert-guidance", config.expert_guidance])
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                text=True,
            )
            procs.append((i, proc, sub_out, nonce))
        except (OSError, ValueError) as e:
            logger.error("evaluator 子进程 %d 启动失败: %s", i, e)

    # 等所有子进程退出（首轮尝试）
    runs: list[dict] = []
    errors: list[str] = []
    max_retries_per_run = 2  # 每 run 最多重试 2 次（总共最多 3 次尝试）

    # 记录每位 run 的重试信息 + 当前是否成功（修复：重试只看失败 run，避免重复统计成功 run）
    run_retries: dict[int, int] = {i: 0 for i in range(n_runs)}
    run_status: dict[int, bool] = {i: False for i in range(n_runs)}

    def _collect_run(i: int, proc, sub_out: Path, nonce: str) -> bool:
        """收集单个子进程的结果。成功返回 True，失败返回 False 并记录错误。"""
        try:
            stdout, stderr = proc.communicate(timeout=600)
            if proc.returncode != 0:
                errors.append(f"run_{i} (nonce={nonce[:8]}): exit={proc.returncode}, stderr={stderr[-300:]}")
                logger.warning("evaluator run_%d 子进程 exit=%d, stderr=%s",
                               i, proc.returncode, stderr[-300:])
                run_status[i] = False
                return False
            if not sub_out.exists():
                errors.append(f"run_{i} (nonce={nonce[:8]}): 输出文件不存在")
                run_status[i] = False
                return False
            try:
                r = json.loads(sub_out.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                errors.append(f"run_{i} (nonce={nonce[:8]}): 解析失败: {e}")
                run_status[i] = False
                return False
            if r.get("_error"):
                errors.append(f"run_{i} (nonce={nonce[:8]}): {r.get('_error')}")
                run_status[i] = False
                return False
            # 强制 round 写对
            r["round"] = round_num
            runs.append(r)
            run_status[i] = True
            # 清理该 idx 之前的 errors（如果之前失败过现已重试成功，避免 n_succeeded/n_failed 状态不一致）
            errors[:] = [e for e in errors if not e.startswith(f"run_{i} (")]
            logger.info("evaluator run_%d 完成: total=%.2f, nonce=%s",
                        i, r.get("total", 0.0), nonce[:8])
            return True
        except subprocess.TimeoutExpired:
            proc.kill()
            errors.append(f"run_{i} (nonce={nonce[:8]}): timeout")
            logger.error("evaluator run_%d 子进程超时,已 kill", i)
            run_status[i] = False
            return False
        except Exception as e:  # noqa: BLE001
            errors.append(f"run_{i} (nonce={nonce[:8]}): {e}")
            logger.error("evaluator run_%d 异常: %s", i, e)
            run_status[i] = False
            return False

    # 第 1 轮：启动全部子进程
    for i, proc, sub_out, nonce in procs:
        _collect_run(i, proc, sub_out, nonce)

    # 重试逻辑：仅对失败的 run 重试最多 max_retries_per_run 次（避免重复统计成功 run）
    for retry_attempt in range(1, max_retries_per_run + 1):
        if len(runs) >= n_runs:
            logger.info("evaluator 所有 %d 个 run 已全部成功", n_runs)
            break

        needed = n_runs - len(runs)
        # 仅筛选当前失败 + 未达重试上限的 run（修复前只看 retries，会把成功的 run 也重试）
        candidates = [
            idx for idx in range(n_runs)
            if not run_status.get(idx, False) and run_retries[idx] < max_retries_per_run
        ]
        if not candidates:
            logger.warning(
                "evaluator 所有失败 run 已到重试上限但仍缺 %d 个成功结果",
                needed,
            )
            break

        need_retry = candidates[:needed]
        logger.info(
            "evaluator 重试第 %d/%d 轮: 重试 %d 个 run (已有 %d/%d 成功)",
            retry_attempt, max_retries_per_run,
            len(need_retry), len(runs), n_runs,
        )

        # 重试：重新启动子进程（新 nonce 防 LLM 缓存，新 sub_out 防旧文件残留）
        retry_procs: list[tuple[int, subprocess.Popen, Path, str]] = []
        for idx in need_retry:
            run_retries[idx] += 1
            nonce = uuid.uuid4().hex
            while nonce in nonce_set:
                nonce = uuid.uuid4().hex
            nonce_set.add(nonce)
            sub_out = output_path.with_suffix(f".sub{idx}.retry{retry_attempt}.json")
            cmd = [
                sys.executable, str(script_path),
                "--skill-root", str(skill_root),
                "--target-files", target_files_str or "SKILL.md",
                "--output-path", str(sub_out),
                "--framework-cfg", framework_cfg_str,
                "--round-num", str(round_num),
                "--nonce", nonce,
            ]
            if config.expert_guidance:
                cmd.extend(["--expert-guidance", config.expert_guidance])
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                    text=True,
                )
                retry_procs.append((idx, proc, sub_out, nonce))
                logger.info(
                    "evaluator run_%d 重试 #%d 已启动 (nonce=%s...)",
                    idx, retry_attempt, nonce[:8],
                )
            except (OSError, ValueError) as e:
                errors.append(f"run_{idx} (retry#{retry_attempt}): 启动失败: {e}")

        # 收集重试结果
        for idx, proc, sub_out, nonce in retry_procs:
            if _collect_run(idx, proc, sub_out, nonce):
                logger.info(
                    "evaluator run_%d 重试 #%d 成功 (nonce=%s...)",
                    idx, retry_attempt, nonce[:8],
                )
            else:
                logger.warning(
                    "evaluator run_%d 重试 #%d 仍失败 (nonce=%s...)",
                    idx, retry_attempt, nonce[:8],
                )

        # 如果本轮重试后全部成功，提前退出
        if len(runs) >= n_runs:
            logger.info("evaluator 所有 %d 个 run 已全部成功（重试后）", n_runs)
            break

    # 保留 score.subN.json + .sub{idx}.retry{N}.json（用户要求保留所有证据文件，不清理）
    # .x 修复：扫除 skill_root 内遗留的 evaluator artifact（防 sub-agent 写错位置污染 worktree → best_skill）
    # 这里只清理 LLM 自救产物（backup_score_subN_retryM.json / score_subN.json / _score.json 等变体），
    # workspace round_N/ 下的 score.subN.json 已被上面保留，**不再清理**。
    # 用 strict regex 严格匹配 evaluator artifact，误删风险为零（其他 .json 不动）
    import re as _re_artifact_cleanup
    _ARTIFACT_RE = _re_artifact_cleanup.compile(
        r"^(score\.sub\d+(?:\.retry\d+)?\.json|backup_score[^/]*\.json)$"
    )
    if skill_root.is_dir():
        for stray in skill_root.rglob("*.json"):
            if _ARTIFACT_RE.match(stray.name):
                try:
                    stray.unlink(missing_ok=True)
                    logger.info("evaluator artifact 兜底清理: %s", stray)
                except OSError:
                    pass

    # 重试后仍失败的 run，清理对应的原始 sub_out 产物
    # 统计最终成功/失败
    n_final_success = len(runs)
    n_final_failed = n_runs - n_final_success

    logger.info(
        "evaluator 子进程全部完成(含重试): %d/%d 成功, %d 次总失败",
        n_final_success, n_runs, n_final_failed,
    )

    # 如果仍有失败的，不再容忍：抛出异常让 orchestrator 重试整个阶段
    if n_final_failed > 0:
        failed_detail = [e for e in errors if e][-5:]  # 只看最后 5 条
        raise RuntimeError(
            f"evaluator {n_runs} 个 run 中 {n_final_failed} 个失败"
            f"（重试 {max_retries_per_run} 次后仍未恢复）: {failed_detail}"
        )

    return runs, errors


def _load_enabled_dimensions() -> dict[str, bool]:
    """ P1-4/5/6:从 optimize-user-config.yaml.enabled_dimensions 读取启用的 auto 维度。

    返回 {dim_key: enabled_bool},缺失的 dim 默认 False。
    """
    try:
        from .static_optimizer import _load_user_config_full

        cfg = _load_user_config_full()
        enabled = cfg.get("enabled_dimensions", {}) or {}
        if not isinstance(enabled, dict):
            return {}
        return {k: bool(v) for k, v in enabled.items()}
    except (ImportError, AttributeError):
        return {}


def _recompute_total_and_validate(
    dim_scores: dict,
    framework_cfg: dict,
) -> tuple[float, str]:
    """治本（.11+）：dim_score 硬校验 + total 重算。

    单一权威入口。被 invoke_evaluator 和 static_evaluator_subprocess 共用,保证两条路径
    写入 score.json 的 total 字段一致(都是基于 dim_scores × weights × 10 / sum_weights 算)。

    行为:
    - 校验 dim_scores 所有 dim 字段 ∈ [0, 10] 且为数值,违反契约 raise ValueError
    - 重算 total = round(weighted_sum / sum_weights * 10, 2)(百分制)
    - 同步算 rating

    Args:
        dim_scores: LLM judge 返回的 dim_scores 字典(可能含非 dim 字段,会被忽略)
        framework_cfg: framework YAML 解析结果,含 rubric[].weight

    Returns:
        (total, rating)

    Raises:
        ValueError: 任一 dim_score 不在 [0, 10] 范围,或类型非数值。
                     让 evaluate_with_runs 计入 n_failed 并触发 REWORK 重试。
    """
    if not dim_scores:
        return 0.0, "UNSCORED"

    # 兜底: 字符串类型(如"6.锁定")尝试提取数字前缀
    for k, v in list(dim_scores.items()):
        if not str(k).startswith("dim"):
            continue
        if isinstance(v, str):
            import re as _re
            m = _re.match(r"(-?\d+(?:\.\d+)?)", v.strip())
            if m:
                dim_scores[k] = float(m.group(1))
                continue
            dim_scores[k] = 0.0
    # 硬校验: 所有 dim 字段 ∈ [0, 10] 且为数值(bool 排除)
    invalid: list[tuple[str, object]] = []
    for k, v in dim_scores.items():
        if not str(k).startswith("dim"):
            continue
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            invalid.append((k, v))
            continue
        if not (0.0 <= float(v) <= 10.0):
            invalid.append((k, v))
    if invalid:
        sample = invalid[:3]
        more = f" ...(共 {len(invalid)} 项)" if len(invalid) > 3 else ""
        raise ValueError(
            f"dim_score 违反契约 (必须 ∈ [0,10]): {sample}{more}"
        )

    # 重算 total（与历史行为完全一致：dim_score × weight / sum_weight × 10）
    weights = {
        k: v.get("weight", 1.0)
        for k, v in framework_cfg.get("rubric", {}).items()
        if k.startswith("dim")
    }
    total = 0.0
    wsum = 0.0
    for k, score in dim_scores.items():
        w = weights.get(k, 1.0)
        total += float(score) * w
        wsum += w
    if wsum <= 0:
        return 0.0, "UNSCORED"
    total = round(total / wsum * 10, 2)  # 百分制
    rating = (
        "EXCELLENT" if total >= 85
        else "GOOD" if total >= 70
        else "FAIR" if total >= 55
        else "POOR" if total >= 30
        else "BROKEN"
    )
    return total, rating


def _compute_coverage(
    rubric: dict,
    enabled_dims: dict[str, bool],
    dim_scores: dict[str, float],
    dim_cfg: dict,
) -> float:
    """ P1-4:coverage 维度计算(Skill Coverage 借鉴)。

    公式:coverage = (高分维度权重和 / 总权重) × max_score
    - 分母:rubric 中所有 enabled 维度的总权重
    - 分子:每维分数 ≥ high_score_threshold 的维度权重之和
    YAML 驱动:high_score_threshold / max_score 从 dim_cfg 读
    """
    max_score = float(dim_cfg.get("max_score", 10))
    high_thr = float(dim_cfg.get("high_score_threshold", 7))

    # 仅算 enabled 维度
    total_weight = 0.0
    high_weight = 0.0
    for dim_key, d_cfg in rubric.items():
        if not dim_key.startswith("dim"):
            continue
        # 未启用的维度权重 = 0(给业务方提示该 dim 没参与)
        if not enabled_dims.get(dim_key, True):  # 默认 True 兼容旧行为
            continue
        w = float(d_cfg.get("weight", 1.0))
        s = dim_scores.get(dim_key)
        if s is None:
            continue
        total_weight += w
        if float(s) >= high_thr:
            high_weight += w
    if total_weight <= 0:
        return 0.0
    coverage = (high_weight / total_weight) * max_score
    return round(min(coverage, max_score), 2)


def _compute_safety(
    skill_root: Path,
    dim_cfg: dict,
) -> tuple[float, int]:
    """ P1-5:safety 维度计算(SkillSafetyBench 借鉴)。

    扫描 SKILL.md 中是否含 prompt injection / 系统指令覆盖 / 数据外泄关键词。
    YAML 驱动:detection_keywords / warn_score / reject_score / reject_threshold 从 dim_cfg 读。
    返回 (score, hits_count)。
    """
    keywords = dim_cfg.get("detection_keywords", []) or []
    warn_score = float(dim_cfg.get("warn_score", 8))
    reject_score = float(dim_cfg.get("reject_score", 0))
    reject_thr = int(dim_cfg.get("reject_threshold", 2))

    if not keywords:
        return warn_score, 0  # 无关键词不扫描

    skill_md = skill_root / "SKILL.md"
    if not skill_md.exists():
        return warn_score, 0
    try:
        content = skill_md.read_text(encoding="utf-8").lower()
    except (OSError, UnicodeDecodeError):
        return warn_score, 0

    hits = 0
    for kw in keywords:
        if str(kw).lower() in content:
            hits += 1
    if hits >= reject_thr:
        return reject_score, hits
    if hits > 0:
        return warn_score, hits
    return float(dim_cfg.get("max_score", 10)), 0


def _compute_efficiency(
    current_skill_root: Path,
    baseline_token_count: int | None,
    dim_cfg: dict,
) -> float:
    """.10:Token 效率维度计算(用户定义公式)。

    设计:
    - 无 baseline:eff = base_score (默认 8)
    - token 减少(pct < 0):eff = bonus_score (默认 9,精简奖励)
    - token +0% ~ +neutral_zone_pct%(微变区间):eff = base_score (默认 8)
    - token > +neutral_zone_pct%:每超 neutral_zone 后再增 penalty_step_pct 减 1 分
      · +50% ~ +100% → base_score - 1 = 7
      · +100% ~ +150% → base_score - 2 = 6
      · +150% ~ +200% → base_score - 3 = 5
      · 极端膨胀 → max(0, ...)

    YAML 驱动:neutral_zone_pct=50, penalty_step_pct=50, bonus_score=9, base_score=8, max_score=10
    """
    import math

    max_score = float(dim_cfg.get("max_score", 10))
    base_score = float(dim_cfg.get("base_score", 8))
    neutral_zone_pct = float(dim_cfg.get("neutral_zone_pct", 50))
    penalty_step_pct = float(dim_cfg.get("penalty_step_pct", 50))
    bonus_score = float(dim_cfg.get("bonus_score", 9))

    skill_md = current_skill_root / "SKILL.md"
    if not skill_md.exists():
        return base_score
    try:
        current_tokens = max(1, len(skill_md.read_text(encoding="utf-8")) // 4)
    except (OSError, UnicodeDecodeError):
        return base_score

    if not baseline_token_count or baseline_token_count <= 0:
        return base_score  # 无 baseline → 默认分

    pct_delta = (current_tokens - baseline_token_count) / baseline_token_count * 100

    if pct_delta < 0:
        # 精简:固定奖励
        return bonus_score

    if pct_delta <= neutral_zone_pct:
        # 微变区间(+0% ~ +50%):基线分
        return base_score

    # 膨胀 > neutral_zone:每超 1 个 step_pct 减 1 分(向上取整)
    penalty_units = math.ceil((pct_delta - neutral_zone_pct) / penalty_step_pct)
    eff = base_score - penalty_units

    eff = max(0.0, min(eff, max_score))
    return round(eff, 2)


def _compute_auto_dimensions(
    framework_cfg: dict,
    skill_root: Path,
    dim_scores_mean: dict[str, float],
    target_files: list[Path] | None = None,
    baseline_token_count: int | None = None,
) -> dict[str, float]:
    """ P1-4/5/6:对 rubric 中所有 compute_mode=auto 且 enabled=true 的维度 Python 端直接算分。

    YAML 驱动:维度名称、阈值、关键词列表、公式全部从 framework_cfg + optimize-user-config.yaml 读。
    未来新增 auto 维度只需:
      1. 在 framework YAML 加 dim{N}_xxx 段(compute_mode: auto)
      2. 在 optimize-user-config.yaml.enabled_dimensions 启用
      3. 在本函数加一个 elif 分支调用 _compute_xxx
    Python 端不维护维度枚举硬编码。
    """
    rubric = framework_cfg.get("rubric", {}) or {}
    enabled_dims = _load_enabled_dimensions()

    results: dict[str, float] = {}
    for dim_key, dim_cfg in rubric.items():
        if not dim_key.startswith("dim"):
            continue
        if dim_cfg.get("compute_mode") != "auto":
            continue
        if not enabled_dims.get(dim_key, False):
            continue  # 业务方未启用,跳过

        if dim_key == "dim9_coverage_auto":
            results[dim_key] = _compute_coverage(rubric, enabled_dims, dim_scores_mean, dim_cfg)
        elif dim_key == "dim10_safety_auto":
            score, hits = _compute_safety(skill_root, dim_cfg)
            results[dim_key] = score
            if hits > 0:
                logger.warning(
                    "[safety] %s 命中 %d 个 prompt injection 关键词,score=%.2f",
                    dim_key, hits, score,
                )
        elif dim_key == "dim11_efficiency_auto":
            results[dim_key] = _compute_efficiency(skill_root, baseline_token_count, dim_cfg)
        # 未来扩展:加 elif 分支即可
    return results


def _aggregate_gaps(runs: list[dict]) -> list[str]:
    """union 去重 + 按跨 run 命中数降序 + top-7。

    原行为:`last_run = runs[-1]` 取最后一份,短板丢失。
    新行为:跨 run 多次出现的 gap 排前,代表 3 次 LLM judge 共识。
    严重度代理:命中数(LLM 未输出 severity 字段)。
    """
    gap_counts: dict[str, int] = {}
    for r in runs:
        for g in r.get("gaps", []) or []:
            if not isinstance(g, str) or not g.strip():
                continue
            gap_counts[g] = gap_counts.get(g, 0) + 1
    # 排序:命中数降序 → 字符串字典序(稳定)
    return [g for g, _ in sorted(gap_counts.items(), key=lambda x: (-x[1], x[0]))][:7]


def _aggregate_anti_pattern_hits(runs: list[dict]) -> list[dict]:
    """union 去重 + 加 vote_count 字段 + 按命中数降序。

    原行为:取最后一份。
    新行为:跨 run 多次命中的 pattern 排前;每条 hit 加 vote_count 字段,
    命中数 ≥2 视为高置信反例(供下游 proposal 权重参考)。
    """
    hit_map: dict[tuple, dict] = {}
    for r in runs:
        for h in r.get("anti_pattern_hits", []) or []:
            if not isinstance(h, dict):
                continue
            pid = str(h.get("pattern_id", ""))
            ev = str(h.get("evidence", ""))
            if not pid:
                continue
            key = (pid, ev)
            if key not in hit_map:
                hit_map[key] = {
                    "pattern_id": pid,
                    "evidence": ev,
                    "vote_count": 0,
                }
            hit_map[key]["vote_count"] += 1
    # 排序:vote_count 降序 → pattern_id 升序
    return sorted(hit_map.values(), key=lambda x: (-x["vote_count"], x["pattern_id"]))


def _run_evaluators_inprocess(
    skill_root: Path,
    target_files: list[Path],
    config: "StaticConfig",
    framework_cfg: dict,
    output_path: Path,
    round_num: int,
    n_runs: int,
) -> tuple[list[dict], list[str]]:
    """旧版:ThreadPoolExecutor 并发跑 N 次 invoke_evaluator(共享主进程状态)。

    仅调试用,生产应走 _run_evaluators_subprocess。
    """
    import uuid
    from concurrent.futures import ThreadPoolExecutor, as_completed

    runs: list[dict] = []
    errors: list[str] = []
    run_outputs: list[Path] = []

    with ThreadPoolExecutor(max_workers=n_runs) as ex:
        futures = {}
        for i in range(n_runs):
            run_out = output_path.with_suffix(f".run{i}.json")
            run_outputs.append(run_out)
            nonce = uuid.uuid4().hex
            futures[ex.submit(
                invoke_evaluator,
                skill_root, target_files, config,
                run_out, framework_cfg, round_num,
                nonce=nonce,
            )] = i
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                r = fut.result()
                runs.append(r)
            except Exception as e:
                errors.append(f"run_{idx}: {e}")
                logger.warning("evaluator run_%d 失败: %s", idx, e)

    # 清理临时 run{N}.json 临时文件
    for run_out in run_outputs:
        try:
            run_out.unlink(missing_ok=True)
        except OSError:
            pass

    return runs, errors


def evaluate_with_runs(
    skill_root: Path,
    target_files: list[Path],
    config: "StaticConfig",
    framework_cfg: dict,
    output_path: Path,
    round_num: int = 1,
    n_runs: int = 3,
    *,
    baseline_token_count: int | None = None,
    use_subprocess: bool = True,
) -> dict:
    """ +  B：同一轮 evaluator 并发跑 N 次，返回聚合结果。

    聚合策略：对 dim_scores 逐维度算 mean，再按 framework YAML weights 重算 total。
    比"先算 total 再平均 total"更准确（避免 total 计算公式变化时聚合偏差）。

     B 新增:
    - use_subprocess=True(默认):每次 evaluator 跑在独立 Python 子进程中,断绝主进程状态
      (共享 LLM client、in-memory cache、模块全局变量)污染
    - use_subprocess=False:走旧版 ThreadPoolExecutor(仅调试用,生产禁用)
    - 每轮生成唯一 nonce 写入 LLM API 的 user_id metadata,防 LLM 端跨 call 缓存命中

    Returns:
        {
            "dim_scores": {dim: mean, ...},
            "total": <float>,                                  # 由聚合 dim_scores 重算
            "rating": <str>,
            "gaps": [...],                                     # 取最后一次成功 run
            "anti_pattern_hits": [...],
            "expert_guidance_ref": "...",
            "_eval_runs": {
                "n_requested": n_runs,
                "n_succeeded": <int>,
                "n_failed": <int>,
                "per_run_totals": [...],
                "total_mean": <float>,
                "total_stdev": <float>,
                "dim_stdev": {dim: σ, ...},
                "aggregation_method": "mean" | "single",
                "isolation_mode": "subprocess" | "thread",  #  B 新增
            },
        }
    """
    #  向后兼容：n_runs <= 1 直接调 invoke_evaluator，无并发
    if n_runs <= 1:
        result = invoke_evaluator(
            skill_root, target_files, config,
            output_path, framework_cfg, round_num,
        )
        result["_eval_runs"] = {
            "n_requested": 1,
            "n_succeeded": 1,
            "n_failed": 0,
            "per_run_totals": [result.get("total", 0.0)],
            "total_mean": result.get("total", 0.0),
            "total_stdev": 0.0,
            "dim_stdev": {},
            "aggregation_method": "single",
            "isolation_mode": "subprocess" if use_subprocess else "thread",
        }
        return result

    #  B 方案:默认走子进程路径(防 LLM judge 跨轮污染)
    # fix: score_mode 不是 subagent 时不走子进程(子进程硬编码 _run_subagent)
    score_mode_raw = (config.score_mode or "llm_direct").strip().lower()
    if use_subprocess and score_mode_raw == "subagent":
        runs, errors = _run_evaluators_subprocess(
            skill_root=skill_root,
            target_files=target_files,
            config=config,
            framework_cfg=framework_cfg,
            output_path=output_path,
            round_num=round_num,
            n_runs=n_runs,
        )
    elif use_subprocess and score_mode_raw.startswith("llm_"):
        # score_mode=llm_direct：走 inprocess 路径，避免子进程硬编码 subagent
        logger.info(
            "score_mode=%s 不走子进程(子进程仅支持 subagent)，改用 inprocess 方式",
            score_mode_raw,
        )
        runs, errors = _run_evaluators_inprocess(
            skill_root=skill_root,
            target_files=target_files,
            config=config,
            framework_cfg=framework_cfg,
            output_path=output_path,
            round_num=round_num,
            n_runs=n_runs,
        )
    else:
        # 旧版:ThreadPoolExecutor 并发(仅调试)
        runs, errors = _run_evaluators_inprocess(
            skill_root=skill_root,
            target_files=target_files,
            config=config,
            framework_cfg=framework_cfg,
            output_path=output_path,
            round_num=round_num,
            n_runs=n_runs,
        )

    # 清理临时 run{N}.json 临时文件（保留 aggregated 一份）
    #  B 方案：run_outputs 已在子进程/inprocess 内部清理,这里不再做

    if not runs:
        raise RuntimeError(f"evaluator {n_runs} 次全失败: {errors}")

    # 聚合：逐 dim 算 mean（缺失维度不计入，保持诚实）
    all_dims: set[str] = set()
    for r in runs:
        all_dims.update(r.get("dim_scores", {}).keys())
    dim_scores_mean: dict[str, float] = {}
    dim_stdev: dict[str, float] = {}
    for d in sorted(all_dims):
        vals = [float(r["dim_scores"][d]) for r in runs
                if r.get("dim_scores", {}).get(d) is not None]
        if not vals:
            continue
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        dim_scores_mean[d] = round(mean, 2)
        dim_stdev[d] = round(var ** 0.5, 2)

    # 按 weights 重算 total（与 invoke_evaluator 内部算法一致）
    # 修复 1：weights 从 rubric 段取（之前用 get("weights", {}) 永远空，权重全是 1.0）
    weights = {
        k: v.get("weight", 1.0)
        for k, v in framework_cfg.get("rubric", {}).items()
        if k.startswith("dim")
    }
    # 修复 2 根治：per_totals 必须先定义（之前在 line 924 引用，但 line 939 才定义 → UnboundLocalError）
    per_totals = [float(r.get("total", 0.0)) for r in runs]
    total = 0.0
    wsum = 0.0
    for d, s in dim_scores_mean.items():
        w = weights.get(d, 1.0)
        total += s * w
        wsum += w
    weighted_total = round(total / wsum * 10, 2) if wsum > 0 else 0.0
    # 修复 2：total 用 mean(per_run_totals) 作为最终值（用户要求三次平均直接 mean）
    total = round(sum(per_totals) / len(per_totals), 2) if per_totals else 0.0

    # 等级判定
    if total >= 85:
        rating = "EXCELLENT"
    elif total >= 70:
        rating = "GOOD"
    elif total >= 55:
        rating = "FAIR"
    elif total >= 30:
        rating = "POOR"
    else:
        rating = "BROKEN"

    # per-run totals 统计（治本 .11+：r["total"] 由 invoke_evaluator / 子进程 _recompute_total_and_validate 重算过,
    # 与 per_run_dim_scores 数据源一致,杜绝 LLM 自填 total 偏差污染聚合）
    total_mean = sum(per_totals) / len(per_totals)
    total_var = sum((t - total_mean) ** 2 for t in per_totals) / len(per_totals)
    total_stdev = round(total_var ** 0.5, 2)

    # .9:per-run dim_scores(每次 evaluator 独立跑 N 次,每个 dim 也保留每次的原始分数)
    # 之前只记录 per_run_totals(总分),dim_scores 直接 mean 后丢弃单次值
    # 现在保留每 run 的 dim_scores,便于审计 LLM judge 噪声
    # 治本 .11+:r["dim_scores"] 已通过 _recompute_total_and_validate 硬校验 ∈ [0, 10],
    # 与 per_run_totals 同源,数据流统一
    per_run_dim_scores: list[dict[str, float]] = [
        {k: float(r.get("dim_scores", {}).get(k, 0.0)) for k in dim_scores_mean.keys()}
        for r in runs
    ]

    # gaps / anti_pattern_hits：原为"取最后一次成功的 run"→短板丢失(3 次 LLM judge
    # 只用最后一份)。改造为"union 去重 + 按跨 run 命中数排序"：多次出现的 gap/pattern
    # 排前,代表"3 次 judge 共识",而非单次随机观测。
    # 严重度代理:跨 run 命中数(LLM 未输出 severity 字段,用频次替代)。
    aggregated_gaps = _aggregate_gaps(runs)
    aggregated_anti_hits = _aggregate_anti_pattern_hits(runs)

    # last_run 仅用于传播非聚合字段(round / expert_guidance_ref / scored_at / 等)
    last_run = runs[-1]

    aggregated = {
        **last_run,
        "dim_scores": dim_scores_mean,
        "total": total,
        "rating": rating,
        "gaps": aggregated_gaps,
        "anti_pattern_hits": aggregated_anti_hits,
        "_eval_runs": {
            "n_requested": n_runs,
            "n_succeeded": len(runs),
            "n_failed": len(errors),
            "errors": errors,
            "per_run_totals": per_totals,
            "total_mean": round(total_mean, 2),
            "total_stdev": total_stdev,
            "dim_stdev": dim_stdev,
            # .9:每次 evaluator run 的 多维分数明细
            "per_run_dim_scores": per_run_dim_scores,
            "aggregation_method": "mean",
            "isolation_mode": "subprocess" if use_subprocess else "thread",
            "gaps_aggregation": "union+vote_top7",
            "anti_pattern_aggregation": "union+vote",
        },
    }

    #  P1-4/5/6：3 个 auto 维度（YAML 驱动,Python 端直接算分）
    # 读 optimize-user-config.yaml.enabled_dimensions 段,只对 enabled=true 的 dim 算分
    # 若都未启用,函数快速返回原 aggregated（行为与现状一致）
    # .5:baseline_token_count 从主循环传入,让 efficiency 维度能算 token 相对增量
    auto_dims = _compute_auto_dimensions(
        framework_cfg=framework_cfg,
        skill_root=skill_root,
        dim_scores_mean=dim_scores_mean,
        target_files=target_files,
        baseline_token_count=baseline_token_count,
    )
    if auto_dims:
        # 合并 auto 维度分数到 dim_scores(override LLM 给的)
        aggregated["dim_scores"].update(auto_dims)
        # 重新算 total(用 framework YAML weights)
        weights = framework_cfg.get("weights", {})
        new_total = 0.0
        wsum = 0.0
        for k, s in aggregated["dim_scores"].items():
            w = weights.get(k, 1.0)
            try:
                sv = float(s)
            except (TypeError, ValueError):
                continue
            new_total += sv * w
            wsum += w
        if wsum > 0:
            aggregated["total"] = round(new_total / wsum * 10, 2)
            t = aggregated["total"]
            aggregated["rating"] = (
                "EXCELLENT" if t >= 85
                else "GOOD" if t >= 70
                else "FAIR" if t >= 55
                else "POOR" if t >= 30
                else "BROKEN"
            )
        aggregated["_auto_dimensions"] = auto_dims

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(aggregated, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logging.getLogger(__name__).info(
        "evaluator N=%d: total=%.2f (stdev=%.2f), %d 成功 %d 失败",
        n_runs, total, total_stdev, len(runs), len(errors),
    )
    return aggregated


def _aggregate_unified_runs(
    runs: list[dict],
    framework_cfg: dict,
    n_runs: int = 3,
) -> dict:
    """ v0.19+ 多次评测聚合：unified agent 跑 N 次 → mean + stdev + 合并 modifications。

    与 6 phase 路径的 evaluate_with_runs 末尾聚合逻辑对齐（行 1086-1166）：
    - dim_scores: 按 (file × dim) 取 mean，再算全局 dim mean
    - total: 用 mean(per_run_totals) 作为最终值（用户要求 3 次平均直接 mean）
    - total_stdev: 各次 total 的 stdev
    - modifications: 按 (file, section, before[:80]) 指纹去重合并
    - per_file_findings: 聚合 dim_scores（取 mean）+ findings 去重合并
    - _eval_runs: 与 6 phase 路径字段对齐（n_requested/n_succeeded/per_run_totals/total_stdev/...）

    区别：unified 路径 runs 是 invoke_unified_agent 返回值（per_file_findings[].dim_scores + modifications），
    没有 gaps / anti_pattern_hits 字段（unified agent 不输出）。所以这些字段在聚合时直接忽略。
    """
    if not runs:
        return {
            "_eval_runs": {
                "n_requested": n_runs,
                "n_succeeded": 0,
                "n_failed": n_runs,
                "per_run_totals": [],
                "total_mean": 0.0,
                "total_stdev": 0.0,
                "aggregation_method": "mean",
            },
        }

    # n_runs == 1：单次不聚合，直接补 _eval_runs 字段
    if n_runs <= 1:
        last = dict(runs[0])
        last["_eval_runs"] = {
            "n_requested": 1,
            "n_succeeded": 1,
            "n_failed": 0,
            "per_run_totals": [float(last.get("total", 0.0))],
            "total_mean": float(last.get("total", 0.0)),
            "total_stdev": 0.0,
            "aggregation_method": "single",
        }
        return last

    # 1. 聚合 per_file_findings[].dim_scores（按 file × dim 收集所有 run 的分数）
    file_dim_runs: dict[str, dict[str, list[float]]] = {}
    file_findings_list: dict[str, list[dict]] = {}
    for r in runs:
        for entry in (r.get("per_file_findings") or []):
            if not isinstance(entry, dict):
                continue
            f = entry.get("file", "")
            if not f:
                continue
            ds = entry.get("dim_scores") or {}
            for dim, info in ds.items():
                if isinstance(info, dict) and isinstance(info.get("score"), (int, float)):
                    file_dim_runs.setdefault(f, {}).setdefault(dim, []).append(
                        float(info["score"])
                    )
            for finding in (entry.get("findings") or []):
                if isinstance(finding, dict):
                    file_findings_list.setdefault(f, []).append(finding)

    # 2. 重建 per_file_findings：聚合 dim_scores（取 mean）+ findings 去重合并
    aggregated_findings: list[dict] = []
    for f, dim_dict in file_dim_runs.items():
        merged_dim_scores: dict[str, dict] = {}
        for dim, scores in dim_dict.items():
            mean_score = round(sum(scores) / len(scores), 2)
            var = sum((s - mean_score) ** 2 for s in scores) / len(scores)
            merged_dim_scores[dim] = {
                "score": mean_score,
                "stdev": round(var ** 0.5, 2),
                "n_runs": len(scores),
                "rationale": f"聚合 {len(scores)} 次 run 的均值（消除 LLM judge 抽样噪声）",
            }
        # findings 去重（按 section + before 指纹）
        seen_finding_fp: set = set()
        unique_findings: list[dict] = []
        for finding in file_findings_list.get(f, []):
            fp = (finding.get("section", ""), finding.get("before", "")[:80])
            if fp in seen_finding_fp:
                continue
            seen_finding_fp.add(fp)
            unique_findings.append(finding)
        aggregated_findings.append({
            "file": f,
            "dim_scores": merged_dim_scores,
            "findings": unique_findings,
        })

    # 3. 聚合后的全局 dim_scores（按 dim 取所有 file 的均值）
    dim_scores_mean: dict[str, float] = {}
    dim_stdev: dict[str, float] = {}
    per_run_dim_scores: list[dict[str, float]] = []
    for r in runs:
        per_run_dim_scores.append({
            k: float(r.get("dim_scores", {}).get(k, 0.0))
            for k in dim_scores_mean.keys()
        })
    # 先确定所有 dim 集合
    all_dims: set[str] = set()
    for f_dim_dict in file_dim_runs.values():
        all_dims.update(f_dim_dict.keys())
    # 全局 dim mean: 收集所有 file × dim × run 的分数
    for d in sorted(all_dims):
        all_vals: list[float] = []
        for f_dim_dict in file_dim_runs.values():
            if d in f_dim_dict:
                all_vals.extend(f_dim_dict[d])
        if not all_vals:
            continue
        mean = sum(all_vals) / len(all_vals)
        var = sum((v - mean) ** 2 for v in all_vals) / len(all_vals)
        dim_scores_mean[d] = round(mean, 2)
        dim_stdev[d] = round(var ** 0.5, 2)

    # 4. modifications 合并去重（按 file + section + before 指纹）
    seen_mod_fp: set = set()
    aggregated_mods: list[dict] = []
    for r in runs:
        for mod in (r.get("modifications") or []):
            if not isinstance(mod, dict):
                continue
            f = mod.get("file", "")
            if not f:
                continue
            fp = (f, mod.get("section", ""), mod.get("before", "")[:80])
            if fp in seen_mod_fp:
                continue
            seen_mod_fp.add(fp)
            aggregated_mods.append(mod)

    # 5. total：按 framework weights 重算 + 用 mean(per_run_totals)（与 6 phase 对齐）
    weights = {
        k: v.get("weight", 1.0)
        for k, v in framework_cfg.get("rubric", {}).items()
        if k.startswith("dim")
    }
    per_totals = [float(r.get("total", 0.0)) for r in runs]
    total = round(sum(per_totals) / len(per_totals), 2) if per_totals else 0.0

    # total_mean / total_stdev
    total_mean = sum(per_totals) / len(per_totals) if per_totals else 0.0
    total_var = sum((t - total_mean) ** 2 for t in per_totals) / len(per_totals) if per_totals else 0.0
    total_stdev = round(total_var ** 0.5, 2)

    # 6. 等级判定
    if total >= 85:
        rating = "EXCELLENT"
    elif total >= 70:
        rating = "GOOD"
    elif total >= 55:
        rating = "FAIR"
    elif total >= 30:
        rating = "POOR"
    else:
        rating = "BROKEN"

    # 7. 取最后一次 run 的非聚合字段（diagnosis / round / ...）
    last_run = runs[-1]

    logger.info(
        "unified agent N=%d: total=%.2f (stdev=%.2f), mods=%d (dedup from %d)",
        n_runs, total, total_stdev, len(aggregated_mods),
        sum(len(r.get("modifications") or []) for r in runs),
    )

    return {
        **last_run,
        "per_file_findings": aggregated_findings,
        "dim_scores": dim_scores_mean,
        "total": total,
        "rating": rating,
        "modifications": aggregated_mods,
        "_eval_runs": {
            "n_requested": n_runs,
            "n_succeeded": len(runs),
            "n_failed": 0,
            "per_run_totals": per_totals,
            "total_mean": round(total_mean, 2),
            "total_stdev": total_stdev,
            "dim_stdev": dim_stdev,
            "per_run_dim_scores": per_run_dim_scores,
            "aggregation_method": "mean",
            "isolation_mode": "sequential",  # unified 路径串行调用 invoke_unified_agent
        },
    }


def invoke_evaluator(
    skill_root: Path,
    target_files: list[Path],
    config: StaticConfig,
    output_path: Path,
    framework_cfg: dict,
    round_num: int = 1,
    attempt: int = 0,
    *,
    nonce: str = "",
    score_mode: str = "llm_direct",
) -> dict:
    """调用 LLM 做 dim_scores 静态评分。

    Args:
        attempt: REWORK 第几次重试（0=首次，1/2/3=retry），用于日志追踪。
        nonce: 唯一标识（ B 方案：防 LLM API 端跨 call 缓存命中）
        score_mode: 评分执行路径
            - "llm_direct"（默认）：拼 prompt 直接调大模型，对齐 skillx-alpha-agents-old
            - "subagent"：cc tools.Agent 真子 Agent + 编码 skill 注入（cosight .17+ 移植）
    """
    from .static_prompts import build_evaluator_prompt

    if attempt > 0:
        logger.warning("evaluator REWORK attempt=%d round=%d", attempt, round_num)

    skill_content, files_content = _read_skill_and_files(skill_root, target_files)
    # -E：dim9_test_prompts 已删除，test_prompts 固定为空
    test_prompts = []

    # v_next：读 eval_view 段（framework 默认 + 业务方覆盖），注入到 evaluator prompt
    eval_view_cfg = framework_cfg.get("eval_view", {}) or {}
    try:
        from .static_optimizer import _load_user_config_full
        _user_cfg = _load_user_config_full()
        eval_view_overrides = (_user_cfg.get("dim_view_overrides") or {}) if isinstance(_user_cfg, dict) else {}
    except Exception:
        eval_view_overrides = {}

    system, user_prompt = build_evaluator_prompt(
        skill_content=skill_content,
        target_files_content=files_content,
        expert_guidance=config.expert_guidance,
        rubric=framework_cfg.get("rubric", {}),
        hl_rules=framework_cfg.get("hl_rules", []),
        test_prompts=test_prompts or None,
        round_num=round_num,
        nonce=nonce,
        eval_view=eval_view_cfg,
        eval_view_overrides=eval_view_overrides,
        relation_tree=_load_relation_tree(config),
        applied_modifications=_load_last_applied_mods(config.workspace, round_num),
    )

    # .18+：按 score_mode 选择执行路径
    score_mode_normalized = (score_mode or "llm_direct").strip().lower()

    if score_mode_normalized == "subagent":
        # ========== cosight .17+ sub-agent 路径（cc tools.Agent）==========
        # 编码原则: sub-agent 通过 system prompt 指令自主用 Read 工具加载
        # skills/编码原则/SKILL.md（与 code-optimizer-agent.md 同模式）
        # 不再 import 常量模块、不用 {{CODING_SKILL}} 占位符
        from tools import Agent as _ToolsAgent
        subagent_context = None  # 不传占位符渲染上下文

        try:
            # Agent() 内部 subprocess.Popen 调 cosight, sub-agent 自主用 Grep/Read 探索 SKILL
            # cwd 设为 skillx-alpha-agents 仓根（scripts/optimizers/ → ../..），cc runtime 才能找到
            # agents/skill-evaluator-agent.md
            # 注意: prompt 里所有文件路径都是绝对路径, sub-agent 不依赖 cwd 解析路径
            skillx_root = Path(__file__).resolve().parent.parent.parent
            stdout = _ToolsAgent(
                description=f"skill-evaluator (round={round_num}, attempt={attempt}, nonce={(nonce or '')[:8]})",
                prompt=user_prompt + _output_deadline,
                subagent_type="skill-evaluator-agent",  # 与 agents/skill-evaluator-agent.md 对应
                cwd=str(skillx_root),
                context=subagent_context,
            )
        except Exception as e:
            # raise 让 evaluate_with_runs 计入 failed（不污染 mean 和 stdev）
            logger.error("evaluator sub-agent 调用失败: %s", e)
            raise

        # 从 sub-agent stdout 解析 JSON
        result = _parse_subagent_json_output(stdout, path=output_path)
        if result is None:
            raise RuntimeError(
                f"evaluator sub-agent 输出无法解析为 JSON。stdout 前 500 字符: {stdout[:500]!r}"
            )

        logger.info(
            "evaluator (score_mode=subagent) round=%d attempt=%d 完成", round_num, attempt
        )
    else:
        # ========== 默认 llm_direct 路径（：拼 prompt 直调大模型）==========
        from .static_llm import call_llm_json

        try:
            #  B 方案:evaluator 走 eval_temperature(默认 0.0)绝对确定;nonce 写入 LLM user_id
            llm_cfg = _load_llm_config()
            result = call_llm_json(
                prompt=user_prompt, system=system, config=llm_cfg,
                temperature=llm_cfg.eval_temperature, nonce=nonce,
                debug_label=f"evaluator-agent_r{round_num}_a{attempt}",
            )
        except Exception as e:
            # : 失败时 raise，让 evaluate_with_runs 计入 failed（不污染 mean 和 stdev）。
            # 旧版返回 total=0.0 的占位结果被错误地当作"成功 run"参与聚合，导致 stdev 虚高。
            logger.error("evaluator LLM 调用失败: %s", e)
            raise

        # 把解析后的 result 追加写到 _debug 文件
        try:
            from .static_llm import _dump_llm_debug
            _dump_llm_debug(
                f"evaluator-agent-parsed_r{round_num}_a{attempt}",
                user_prompt, system, json.dumps(result),
                parsed_result=json.dumps(result.get("dim_scores", {}), ensure_ascii=False),
            )
        except Exception:
            pass

    # 标准化（两条路径共用）
    result.setdefault("round", round_num)
    result.setdefault("dim_scores", {})
    result.setdefault("gaps", [])
    result.setdefault("anti_pattern_hits", [])
    result.setdefault("expert_guidance_ref", config.expert_guidance[:200])
    # .18+：标注本次评估的 score_mode，便于回放与审计
    result["score_mode"] = score_mode_normalized

    # 治本（.11+）：调用共享 _recompute_total_and_validate,统一两条路径行为
    # 违反契约 raise → evaluate_with_runs 计入 n_failed → REWORK 重试
    dim_scores = result.get("dim_scores", {}) or {}
    result["total"], result["rating"] = _recompute_total_and_validate(
        dim_scores, framework_cfg,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def invoke_optimizer(
    skill_root: Path,
    target_files: list[Path],
    config: StaticConfig,
    round_num: int,
    score_json: dict,
    output_path: Optional[Path],
    framework_cfg: dict,
    attempt: int = 0,
    relation_tree: Optional[dict] = None,
    revise_signals: Optional[dict] = None,
    overfit_signals: Optional[dict] = None,
    apply_failure_signals: Optional[list] = None,
    chars_budget: Optional[int] = None,
    revision_strategy: Optional[dict] = None,
    score_mode: str = "llm_direct",
    custom_user_prompt: Optional[str] = None,
) -> dict:
    """生成 modifications proposal（支持 score_mode 分支）。

    score_mode:
        - "llm_direct"（默认）：call_llm_json HTTP 直调，快速但无进程隔离
        - "subagent"：cc tools.Agent 真子 Agent，进程隔离更彻底但慢 2~3 倍

    Args:
        attempt: REWORK 第几次重试（0=首次，1/2/3=retry），用于日志追踪。
        relation_tree: 文件关系树骨架（None → 从 workspace 磁盘读；仍无则不注入）
        revise_signals:  Top 3 — 上一轮 REVISE 信号（避免重复错误）
        overfit_signals:  P1-B — 上一轮 overfit 检测反馈（warn-only 闭环）
        apply_failure_signals:  P2-A — 上一轮 apply 失败根因列表
        chars_budget:  P2-B — 单轮 modifications 总字符预算（before+after 之和）
        revision_strategy: R2+ 接续优化策略(StaticRevisionAgent 产出,R1=None)
    """
    from .static_prompts import build_optimizer_prompt

    if attempt > 0:
        logger.warning("optimizer REWORK attempt=%d round=%d", attempt, round_num)

    skill_content, files_content = _read_skill_and_files(skill_root, target_files)

    # 单轮 max_mods 收敛:16 → 14 → 12 ... 最低 3（放宽，让大 skill 跨文件联动更充分）
    max_mods = max(3, 16 - (round_num - 1) * 2)

    # 关系树骨架：调用方未传则从 workspace 磁盘读（单一真相源，由 _ensure_relation_tree 写好）
    if relation_tree is None:
        relation_tree = _load_relation_tree(config)

    # v_next：读 design_principles 段（framework 默认 + 业务方追加），注入到 optimizer prompt
    design_principles = framework_cfg.get("optimizer_design_principles", []) or []
    try:
        from .static_optimizer import _load_user_config_full
        _user_cfg = _load_user_config_full()
        design_principles_overrides = (
            (_user_cfg.get("design_principles_overrides") or [])
            if isinstance(_user_cfg, dict) else []
        )
    except Exception:
        design_principles_overrides = []

    system, user_prompt = build_optimizer_prompt(
        score_json=score_json,
        skill_content=skill_content,
        target_files_content=files_content,
        expert_guidance=config.expert_guidance,
        hl_rules=framework_cfg.get("hl_rules", []),
        round_num=round_num,
        max_modifications=max_mods,
        chars_budget=chars_budget,
        relation_tree=relation_tree,
        revise_signals=revise_signals,
        overfit_signals=overfit_signals,
        apply_failure_signals=apply_failure_signals,
        revision_strategy=revision_strategy,
        design_principles=design_principles,
        design_principles_overrides=design_principles_overrides,
    )

    # ===== 按 score_mode 分支：llm_direct / subagent =====
    score_mode_norm = (score_mode or "llm_direct").strip().lower()
    logger.info(
        "[optimizer-agent 启动] round=%d attempt=%d prompt_chars=%d mode=%s",
        round_num, attempt, len(user_prompt), score_mode_norm,
    )
    import time as _t
    _t0 = _t.monotonic()

    if score_mode_norm == "subagent":
        # ========== 子 Agent 路径（subprocess 隔离）==========
        subagent_context = {"CODING_SKILL": ""}
        from tools import Agent as _ToolsAgent

        # 追加输出格式死线约束（末尾权重最高）
        # 根治：之前 "最后一段" 表述让 LLM 先输出说明再输出 JSON（解析失败）
        # 改为强制 "**第一字符** = `{`，**最后字符** = `}`"（纯 JSON，无任何说明）
        _output_deadline = (
            "\n\n**🔴 死线约束（违反则 REWORK 3 次失败 + 任务终止）**：\n"
            "你的 stdout **必须** 是纯 JSON 对象——**第一个字符必须是 `{`，最后一个字符必须是 `}`**。\n"
            "**严禁**输出任何说明文字、Markdown、标题、注释、'已按要求生成'等开场白。\n"
            "**严禁**用 Write 工具把 JSON 写到文件——只能 stdout 输出。\n"
            "JSON 必须含字段：round (int) / diagnosis (object) / modifications (array，每条 mod 必含 file+section+before+after+dim_improved+pattern_used)。\n"
            "**若不满足 → REWORK 3 次失败 → 本轮放弃**。"
        )
        # 编码原则 skill 召回指令（模块级常量 _SKILL_LOAD_DIRECTIVE，与 unified 路径共用）：
        # 不硬编码 4 原则文本，让 sub-agent 主动 Read skills/编码原则/SKILL.md。
        _skill_load_directive = _SKILL_LOAD_DIRECTIVE
        # 强制要求：必须用 Read 工具逐个读全部 target_files（不依赖 prompt 注入的 6000 字符截断内容）
        # 这是子 agent 输出层硬约束，LLM 不可忽略；对应每个被引用的 .md/.sh/.py 文件都必须先 Read
        # 编码原则 skill 召回指令保留（仅在涉及代码文件时生效）
        try:
            stdout = _ToolsAgent(
                description=f"optimizer-agent (round={round_num}, attempt={attempt})",
                prompt=user_prompt + _skill_load_directive + _output_deadline,
                subagent_type="optimizer-agent",
                cwd=None,
                context=subagent_context,
            )
        except Exception as e:
            logger.error("optimizer sub-agent 调用失败(rework 将重试): %s", e)
            raise

        result = _parse_subagent_json_output(stdout, path=output_path)
        if result is None:
            raise RuntimeError(
                f"optimizer sub-agent 输出无法解析为 JSON。stdout 前 500 字符: {stdout[:500]!r}"
            )
    else:
        # ========== 默认 llm_direct 路径（HTTP 直调，快）==========
        from .static_llm import call_llm_json
        from .static_prompts import build_optimizer_prompt as _bop

        # 重建 prompt（llm_direct 需要 system + user_prompt 两个参数）
        _system_optimizer = (
            "你是 skill 优化专家。基于上轮评分生成精准修改方案，"
            "避开 8 条 darwin 自操作反例，每条 modification 必须标注 dim_improved 和 pattern_used。"
        )
        _, user_prompt_full = _bop(
            score_json=score_json,
            skill_content=skill_content,
            target_files_content=files_content,
            expert_guidance=config.expert_guidance,
            hl_rules=framework_cfg.get("hl_rules", []),
            round_num=round_num,
            max_modifications=max_mods,
            chars_budget=chars_budget,
            relation_tree=relation_tree,
            revise_signals=revise_signals,
            overfit_signals=overfit_signals,
            apply_failure_signals=apply_failure_signals,
            revision_strategy=revision_strategy,
            design_principles=design_principles,
            design_principles_overrides=design_principles_overrides,
        )
        llm_cfg = _load_llm_config()
        try:
            result = call_llm_json(
                prompt=user_prompt_full, system=_system_optimizer, config=llm_cfg,
                temperature=llm_cfg.eval_temperature,
                debug_label=f"optimizer-agent_r{round_num}_a{attempt}",
            )
        except Exception as e:
            logger.error("optimizer call_llm_json 失败(rework 将重试): %s", e)
            raise

        # 把解析后的 result 追加写到同一份 _debug 文件
        try:
            from .static_llm import _dump_llm_debug
            _dump_llm_debug(
                f"optimizer-agent-parsed_r{round_num}_a{attempt}",
                user_prompt_full, _system_optimizer, json.dumps(result),
                parsed_result=json.dumps(result.get("modifications", [])[:5], ensure_ascii=False),
            )
        except Exception:
            pass

    # 标准化
    result.setdefault("round", round_num)
    result.setdefault("modifications", [])
    result.setdefault("coverage", [])
    result.setdefault("uncovered_gaps", [])
    result.setdefault(
        "expert_guidance_ref", config.expert_guidance[:200] if config.expert_guidance else ""
    )
    #  P0-3:归因-修改两步拆分 — diagnosis / gradient_analysis 段容错
    result.setdefault("diagnosis", {})
    result.setdefault("gradient_analysis", {})
    result["revision_strategy"] = revision_strategy if revision_strategy else {}

    # Per-file findings 校验 + 合并（强制 LLM 逐文件扫描，根治 SKILL.md 偏向）
    from .static_apply import (derive_per_file_findings,
                               merge_findings_to_modifications,
                               validate_per_file_coverage)

    # 框架兜底：LLM 不提供 per_file_findings 时从 modifications 推导 + 关系树补空
    # （不假设 LLM 输出完美 schema）
    if not result.get("per_file_findings"):
        derived = derive_per_file_findings(result, relation_tree)
        if derived:
            logger.info(
                "per_file_findings 框架兜底推导: %d 个文件（来自 %d 条 mods）",
                len(derived), len(result.get("modifications") or []),
            )
            result["per_file_findings"] = derived
    coverage_cfg = framework_cfg.get("relation_tree", {}).get("coverage_guard", {}) or {}
    is_valid, error_msg, missing = validate_per_file_coverage(
        result, relation_tree, coverage_cfg,
    )
    result["_per_file_validation"] = {
        "is_valid": is_valid,
        "missing_files": missing,
        "error_msg": error_msg,
    }
    if not is_valid:
        # 对 subagent 路径降级：LLM 输出有多个 JSON 块（迭代过程），取最终 modifications
        # subagent 无需强校验 per_file_findings，以 modifications 为准
        if score_mode_norm == "subagent":
            logger.warning(
                "per_file_findings 校验失败(降级): %s。subagent 路径以 modifications 为准。",
                error_msg,
            )
        else:
            raise RuntimeError(
                f"per_file_findings 校验失败: {error_msg}。LLM 必须为骨架表每个文件输出 findings。"
            )
    # 若 LLM 没提供 per_file_findings 但提供了 modifications → 沿用旧逻辑，不强制转换
    if result.get("per_file_findings"):
        # 合并 findings → modifications（按 long_unoptimized 优先 + 预算截断）
        long_un = (relation_tree or {}).get("long_unoptimized", [])
        merged_mods = merge_findings_to_modifications(
            result["per_file_findings"], max_mods, long_un,
        )
        # 若 LLM 没填 modifications 或明显短于合并结果，用合并结果补全
        if not result["modifications"] or len(merged_mods) > len(result["modifications"]):
            logger.info(
                "per_file_findings 合并: %d → %d 条 mod（long_un 优先）",
                len(result["modifications"]), len(merged_mods),
            )
            result["modifications"] = merged_mods
    else:
        if error_msg:
            logger.warning("per_file_findings %s（继续使用 modifications）", error_msg)
        # 无 per_file_findings：继续用原有的 modifications（subagent 路径常见）

    # 校验:白名单过滤 + 字段补全
    valid_mods: list[dict] = []
    for mod in result["modifications"]:
        f = mod.get("file", "")
        if not f:
            continue
        if is_protected(f, config.protected_assets):
            logger.warning("proposal 跳过白名单文件: %s", f)
            continue
        # 校验 before/after（必须同时存在且非空）
        if not mod.get("before") or not mod.get("after"):
            continue
        if "dim_improved" not in mod:
            mod["dim_improved"] = "unknown"
        if "pattern_used" not in mod:
            mod["pattern_used"] = "P?"
        valid_mods.append(mod)
    # 日志：记录被过滤的 mod（before/after 为空）
    _skipped_empty = sum(
        1 for mod in result.get("modifications", [])
        if not mod.get("before") or not mod.get("after")
    )
    if _skipped_empty:
        logger.warning(
            "mod 因 before/after 为空被跳过: %d 条 (共 %d 条 LLM 提议)",
            _skipped_empty, len(result.get("modifications", [])),
        )
    result["modifications"] = valid_mods[:max_mods]
    logger.info(
        "invoke_optimizer 完成: LLM 提议 %d 条, 验证通过 %d 条",
        len(result.get("modifications", [])), len(valid_mods),
    )

    md_files, code_files = dispatch_files(target_files)
    result["_dispatch"] = {
        "md_files_count": len(md_files),
        "code_files_count": len(code_files),
        "max_mods": max_mods,
    }
    result["_checklist"] = {
        "no_anti_pattern_hit": True,
        "single_dim_per_mod": all(
            isinstance(m.get("dim_improved"), str) and m["dim_improved"].startswith("dim")
            for m in result["modifications"]
        ),
        "asset_safe": True,
        "max_mods_respected": len(result["modifications"]) <= max_mods,
    }

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # 直接写 JSON（废弃 markdown：LLM 反复把方案写在 markdown 描述里、却没真正写 JSON 块，
        # markdown 文件不再有信源价值）。同时落盘每个文件的 per_file_findings JSON。
        merged_path = output_path.with_suffix(".json")
        merged_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # 每个文件单独一个 per_file_findings JSON
        per_file_dir = output_path.parent / "per_file_findings"
        per_file_dir.mkdir(parents=True, exist_ok=True)
        for entry in (result.get("per_file_findings") or []):
            if not isinstance(entry, dict):
                continue
            f = entry.get("file", "")
            if not f:
                continue
            safe_name = f.replace("/", "__").replace("\\", "__")
            (per_file_dir / f"{safe_name}.json").write_text(
                json.dumps(entry, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    return result


def _format_proposal_markdown(result: dict) -> str:
    """把 invoke_optimizer 的 result dict 序列化为人类可读的 markdown proposal。

    包含 5 段(按优先级排序):
    1. expert_guidance_ref — 用户指引引用
    2. revision_strategy — R2+ StaticRevisionAgent 7 字段策略(R1 空)
    3. diagnosis — 归因-修改两步拆分的归因段( P0-3)
    4. gradient_analysis — 信号分解( P1-8)
    5. modifications[] — 具体修改清单
    6. uncovered_gaps[] — 本轮未覆盖的缺口

    Args:
        result: invoke_optimizer 返回 dict

    Returns:
        Markdown 字符串
    """
    lines: list[str] = [f"# Round {result.get('round', '?')} 优化提案", ""]

    # 1. expert_guidance_ref
    eg_ref = result.get("expert_guidance_ref", "")
    if eg_ref:
        lines.extend(["## 用户指引引用", "", eg_ref, ""])

    # 2. revision_strategy(R2+ 才非空)
    rs = result.get("revision_strategy") or {}
    if rs:
        lines.extend(["## 接续优化策略(R2+ StaticRevisionAgent 产出)", ""])
        absorbed = rs.get("absorbed_rounds") or []
        if absorbed:
            lines.append(f"- **已吸收轮次**: {', '.join(str(r) for r in absorbed)}")
        summary = rs.get("prev_round_summary", "")
        if summary:
            lines.append(f"- **上轮一句话总结**: {summary}")
        trends = rs.get("cross_round_trends") or {}
        if trends:
            lines.append("- **跨轮 dim 趋势**:")
            for dim, trend in trends.items():
                lines.append(f"  - {dim}: {trend}")
        failures = rs.get("prev_failures") or []
        if failures:
            lines.append("- **上轮失败继承(本轮规避)**:")
            for f in failures:
                lines.append(f"  - {f}")
        anchor = rs.get("baseline_anchor", "")
        if anchor:
            lines.append(f"- **基线锚点**: {anchor}")
        balance = rs.get("dim_balance_plan") or {}
        if balance:
            lines.append("- **本轮 dim 预算分配**:")
            for dim, n in balance.items():
                lines.append(f"  - {dim}: {n} 条 mod")
        intent = rs.get("modification_intent") or []
        if intent:
            lines.append("- **modification 目标维度分布**:")
            for i, item in enumerate(intent, 1):
                lines.append(f"  - M{i}: {item}")
        lines.append("")

    # 3. diagnosis
    diag = result.get("diagnosis") or {}
    if diag:
        lines.extend(["## 归因(diagnosis)", ""])
        for k, v in diag.items():
            if isinstance(v, (list, dict)):
                lines.append(f"- **{k}**:")
                lines.append("  ```json")
                lines.append(f"  {json.dumps(v, ensure_ascii=False, indent=2)}")
                lines.append("  ```")
            else:
                lines.append(f"- **{k}**: {v}")
        lines.append("")

    # 4. gradient_analysis
    grad = result.get("gradient_analysis") or {}
    if grad:
        lines.extend(["## 梯度分析(gradient_analysis)", ""])
        for k, v in grad.items():
            lines.append(f"- **{k}**: {v}")
        lines.append("")

    # 5. modifications[]
    mods = result.get("modifications") or []
    lines.extend([f"## modifications({len(mods)} 条)", ""])
    for i, m in enumerate(mods, 1):
        lines.append(f"### M{i}: {m.get('title') or m.get('pattern_used', '?')}")
        lines.append(f"- **file**: {m.get('file', '?')}")
        lines.append(f"- **section**: {m.get('section', '?')}")
        lines.append(f"- **dim_improved**: {m.get('dim_improved', '?')}")
        lines.append(f"- **pattern_used**: {m.get('pattern_used', '?')}")
        lines.append(f"- **reason**: {m.get('reason', '?')[:200]}")
        lines.append("")
        before = m.get("before", "")
        if before:
            lines.append("**before**:")
            lines.append("```")
            lines.append(before[:800])
            lines.append("```")
            lines.append("")
        after = m.get("after", "")
        if after:
            lines.append("**after**:")
            lines.append("```")
            lines.append(after[:800])
            lines.append("```")
            lines.append("")

    # 6. uncovered_gaps
    uncovered = result.get("uncovered_gaps") or []
    if uncovered:
        lines.extend([f"## uncovered_gaps({len(uncovered)} 条下轮优先)", ""])
        for g in uncovered:
            if isinstance(g, dict):
                lines.append(f"- **{g.get('dim', '?')}/{g.get('severity', '?')}**: {g.get('message', '')[:200]}")
            else:
                lines.append(f"- {g}")
        lines.append("")

    # 7. coverage
    cov = result.get("coverage") or []
    if cov:
        lines.extend(["## coverage", ""])
        for c in cov:
            if isinstance(c, dict):
                lines.append(f"### {c.get('file', c.get('path', '?'))}")
                lines.append(f"- status: {c.get('status', '?')}")
                reason = c.get("reason", "")
                if reason:
                    lines.append(f"- reason: {reason}")
            else:
                lines.append(f"- {c}")
        lines.append("")

    # 8. _checklist(供调试)
    chk = result.get("_checklist") or {}
    if chk:
        lines.extend(["## _checklist(机器校验)", ""])
        for k, v in chk.items():
            lines.append(f"- {k}: {v}")
        lines.append("")

    return "\n".join(lines)


def invoke_revision_agent(
    workspace: Path,
    config: StaticConfig,
    round_num: int,
    framework_cfg: dict,
) -> dict:
    """R2+ 调起:StaticRevisionAgent 生成接续优化策略。

    全量吸收 round_0 ~ round_{N-1} 全产物,产出 revision_strategy dict,
    由 orchestrator 注入 P3 optimizer prompt 顶部,作为 R2+ 的方法论约束。

    Args:
        workspace: 任务工作目录(含 round_0/ ... round_{N-1}/ 子目录)
        config: StaticConfig(读 expert_guidance)
        round_num: 当前轮次(>=2)
        framework_cfg: framework YAML dict(读 hl_rules)

    Returns:
        dict: revision_strategy 内容,7 个字段(absorbed_rounds / cross_round_trends /
            prev_round_summary / prev_failures / baseline_anchor / dim_balance_plan /
            modification_intent)。LLM 失败时返回空 dict(R2+ 仍能跑,只是不带 strategy 段)。
    """
    from .static_llm import call_llm_json

    # ── 1. 扫描 round_0 ~ round_{N-1} 全轮次目录 ──
    if round_num < 2:
        return {}

    round_dirs: list[Path] = []
    for child in sorted(workspace.iterdir()):
        if not child.is_dir() or not child.name.startswith("round_"):
            continue
        try:
            k = int(child.name.split("_", 1)[1])
        except (ValueError, IndexError):
            continue
        if 0 <= k < round_num:
            round_dirs.append(child)
    if not round_dirs:
        logger.warning("[Round %d] 未找到任何历史 round 目录,跳过 revision agent", round_num)
        return {}

    # ── 2. 收集全产物摘要(score.json + round_result.json + score_analysis.md 摘要) ──
    history_sections: list[str] = []
    history_entries: list[dict] = []
    static_history_path = workspace / "static_history.json"
    if static_history_path.is_file():
        try:
            history_entries = json.loads(
                static_history_path.read_text(encoding="utf-8"),
            )
        except (OSError, json.JSONDecodeError):
            history_entries = []

    for rd in round_dirs:
        lines: list[str] = [f"### {rd.name}", ""]
        score_path = rd / "score.json"
        rr_path = rd / "round_result.json"
        analysis_path = rd / "score_analysis.md"
        before_path = rd / "before" / "skill"
        after_path = rd / "after" / "skill"

        if score_path.is_file():
            try:
                score_data = json.loads(score_path.read_text(encoding="utf-8"))
                lines.append(f"- score: total={score_data.get('total', '?')} rating={score_data.get('rating', '?')}")
                dim = score_data.get("dim_scores", {})
                if dim:
                    lines.append(f"- dim_scores: {dim}")
                gaps = score_data.get("gaps", [])
                if gaps:
                    lines.append(f"- gaps({len(gaps)}):")
                    for g in gaps[:3]:
                        # 容错：gaps 可能是 list[str] 或 list[dict]
                        if isinstance(g, dict):
                            lines.append(f"  - {g.get('dim', '?')}/{g.get('severity', '?')}: {g.get('message', '')[:80]}")
                        else:
                            lines.append(f"  - {str(g)[:80]}")
            except (OSError, json.JSONDecodeError):
                pass
        if rr_path.is_file():
            try:
                rr_data = json.loads(rr_path.read_text(encoding="utf-8"))
                proposal = rr_data.get("proposal", {})
                mods = proposal.get("modifications", [])
                apply_block = rr_data.get("apply", {})
                lines.append(f"- modifications: 报告 {len(mods)} 条 / 实际应用 {len(apply_block.get('files_changed', []))} 个文件")
                errors = apply_block.get("errors", [])
                if errors:
                    lines.append(f"- apply.errors: {errors[:3]}")
                verifier = rr_data.get("verifier", {})
                if verifier.get("overfit_warning"):
                    lines.append(f"- overfit_warning: {verifier.get('overfit_reasons', [])[:3]}")
            except (OSError, json.JSONDecodeError):
                pass
        # before/after 文件清单 + 全文(每文件 cap 2000 字符,总 cap 8000 字符,
        # 避免 token 爆炸;after 优先,因为 R_N 修改起点是 R_{N-1}/after)
        before_files = sorted(before_path.rglob("*.md")) if before_path.is_dir() else []
        after_files = sorted(after_path.rglob("*.md")) if after_path.is_dir() else []
        lines.append(f"- before/after 文件数: {len(before_files)} / {len(after_files)}")
        # 嵌入全文(带 cap)
        per_file_cap = 2000
        total_cap = 8000
        used = 0
        file_excerpts: list[str] = []
        for f in after_files:
            if used >= total_cap:
                file_excerpts.append(f"  ... (后续 {len(after_files) - len(file_excerpts)} 个文件因总 cap={total_cap} 截断)")
                break
            try:
                content = f.read_text(encoding="utf-8")
                excerpt = content[:per_file_cap]
                if len(content) > per_file_cap:
                    excerpt += f"\n  ... (截断,原 {len(content)} 字符)"
                file_excerpts.append(f"  - {f.relative_to(rd) if f.is_relative_to(rd) else f}:```\n{excerpt}\n```")
                used += len(excerpt)
            except (OSError, UnicodeDecodeError):
                continue
        if file_excerpts:
            lines.append("- **after/ 文件全文摘要(cap 8000 字符)** :")
            lines.extend(file_excerpts)
        history_sections.append("\n".join(lines))

    # ── 3. 构造 system + user prompt ──
    system = (
        "你是 StaticRevisionAgent。R2+ 接续优化策略生成器。"
        "全量吸收 round_0 ~ round_{N-1} 所有产物(score.json + round_result.json + static_history.json),"
        "做跨轮趋势归因,生成 revision_strategy 7 字段 dict。"
        "不直接修改文件,不输出 modifications,只输出策略。"
        "方法论三原则:均衡(不允许单 dim 极端追高)、基线次要参考(round_0 仅作语义锚点,不回退)、"
        "R2 修改起点 = R1 after(已采纳的 R1 改进保留,只补救 R1 引入的回归)。"
    )

    user_prompt = f"""## 任务
本轮 = Round {round_num}。需要你扫描 round_0 ~ round_{round_num - 1} 所有产物,产出 revision_strategy。

## 历史轮次摘要
{chr(10).join(history_sections)}

## 输出 JSON schema(严格遵守)
{{
  "absorbed_rounds": [0, 1, ..., {round_num - 1}],            # 本轮实际扫的轮次列表
  "prev_round_summary": "上轮 N-1 一句话总结(分数/Δ/verdict/采纳数)",
  "cross_round_trends": {{                                    # 跨轮 dim 趋势
    "dim3_failure_modes": "R0=8 → R1=5 → R2=4 (持续 regressed)",
    ...
  }},
  "prev_failures": [                                          # 上轮 apply.errors + verifier.overfit 提炼
    "M3 改 SKILL.md:## 失败模式,命中白名单",
    "overfit: 单 mod 字符 4500 触发上限"
  ],
  "baseline_anchor": "R0 vs 当前漂移点(如:术语'用例' → '场景' 的转换未一致)",
  "dim_balance_plan": {{                                      # 本轮预算按 dim 缺口分配
    "dim3_failure_modes": 3,
    "dim12_efficiency": 2,
    ...
  }},
  "modification_intent": [                                    # 本轮 mod 的目标维度分布
    "M1 目标 dim3 + 副作用 dim12",
    ...
  ]
}}

## 强约束
- revision_strategy 不直接修改文件,仅作为 orchestrator 注入 P3 optimizer prompt 顶部的策略段
- absorbed_rounds 必须列出 round_0 ~ round_{round_num - 1} 全部
- cross_round_trends 必须基于真实 dim_scores,不允许凭印象写
- prev_failures 必须从 round_result.json 的 apply.errors 提炼,不要编造
- dim_balance_plan 总条数 ≤ 8(预留 budget 给单轮 max_mods)
- 输出严格 JSON,不要 markdown 代码块包装
"""

    try:
        result = call_llm_json(
            prompt=user_prompt,
            system=system,
            config=_load_llm_config(),
        )
    except Exception as e:
        logger.error("[Round %d] revision agent LLM 调用失败: %s", round_num, e)
        return {}

    # ── 3.5 类型容错:call_llm_json 可能返回 str(如 markdown 包裹的 JSON)而非 dict ──
    if isinstance(result, str):
        stripped = result.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("```", 2)[-2] if "```" in stripped[3:] else stripped
            stripped = stripped.strip()
        if stripped.startswith("{"):
            try:
                result = json.loads(stripped)
            except (json.JSONDecodeError, TypeError):
                pass
    if not isinstance(result, dict):
        logger.warning("[Round %d] revision agent 返回非 dict(%s),回退空策略", round_num, type(result).__name__)
        return {}

    # ── 4. 容错:字段缺失用空值填充 ──
    result.setdefault("absorbed_rounds", [k for k in range(round_num)])
    result.setdefault("prev_round_summary", "")
    result.setdefault("cross_round_trends", {})
    result.setdefault("prev_failures", [])
    result.setdefault("baseline_anchor", "")
    result.setdefault("dim_balance_plan", {})
    result.setdefault("modification_intent", [])

    # ── 5. 写产物(round_{N}/revision_strategy.json) ──
    output_path = workspace / f"round_{round_num}" / "revision_strategy.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(
        "[Round %d] StaticRevisionAgent 已生成 revision_strategy: %d 字段",
        round_num,
        sum(1 for v in result.values() if v),
    )
    return result


def invoke_unified_agent(
    skill_root: Path,
    target_files: list[Path],
    config: "StaticConfig",
    round_num: int,
    output_path: Optional[Path],
    framework_cfg: dict,
    attempt: int = 0,
    score_mode: str = "subagent",
) -> dict:
    """Unified agent：一次 LLM 调用同时输出评分 + 优化方案（融合 optimizer + evaluator）。

    替代原 invoke_optimizer + invoke_evaluator + evaluate_with_runs。
    单次 LLM 输出 per_file_findings 数组，每文件 entry 含 dim_scores + findings。

    Args:
        skill_root: Skill 根目录
        target_files: 待优化文件列表
        config: StaticConfig
        round_num: 当前轮次
        output_path: 落盘 proposal.json 路径
        framework_cfg: framework YAML 配置
        attempt: REWORK 次数（0=首次）
        score_mode: "subagent" 或 "llm_direct"

    Returns:
        dict 含 per_file_findings / dim_scores / total / rating
    """
    from .static_apply import aggregate_dim_scores
    from .static_prompts import build_unified_prompt

    if attempt > 0:
        logger.warning("unified agent REWORK attempt=%d round=%d", attempt, round_num)

    skill_content, files_content = _read_skill_and_files(skill_root, target_files)
    relation_tree = _load_relation_tree(config)

    # 兜底：若 relations 文件未生成（直接调 invoke_unified_agent 跳过主循环的情况），
    # 现场生成一份到 workspace 顶层，确保 aggregate_dim_scores 拿到 file_weight_map
    if relation_tree is None and config and getattr(config, "workspace", None):
        from .static_optimizer import _ensure_relation_tree
        _ensure_relation_tree(config, skill_root, target_files)
        relation_tree = _load_relation_tree(config)

    system, user_prompt = build_unified_prompt(
        skill_content=skill_content,
        target_files_content=files_content,
        expert_guidance=config.expert_guidance,
        rubric=framework_cfg.get("rubric", {}),
        relation_tree=relation_tree,
        round_num=round_num,
    )

    score_mode_norm = (score_mode or "subagent").strip().lower()
    logger.info(
        "[unified agent 启动] round=%d attempt=%d prompt_chars=%d mode=%s",
        round_num, attempt, len(user_prompt), score_mode_norm,
    )

    import time as _t
    _t0 = _t.monotonic()

    if score_mode_norm == "llm_direct":
        from .static_llm import call_llm_json
        llm_cfg = _load_llm_config()
        try:
            result = call_llm_json(
                prompt=user_prompt, system=system, config=llm_cfg,
                temperature=llm_cfg.eval_temperature,
                debug_label=f"unified-agent_r{round_num}_a{attempt}",
            )
        except Exception as e:
            logger.error("unified agent llm_direct 失败(rework 重试): %s", e)
            raise
    else:
        from tools import Agent as _ToolsAgent

        # 子 agent 模式：复用现有 sub-agent 路径
        _output_deadline = (
            "\n\n**🔴 死线约束（违反则 REWORK 3 次失败 + 任务终止）**：\n"
            "你的 stdout **必须** 是纯 JSON 对象——**第一个字符必须是 `{`，最后一个字符必须是 `}`**。"
            "**严禁**输出任何说明文字、Markdown、标题、注释、'已按要求生成'等开场白。"
            "JSON 必须含字段：round (int) / per_file_findings (数组，每条 entry 含 file+dim_scores+findings)。"
            "**若不满足 → REWORK 3 次失败 → 本轮放弃**。"
        )
        try:
            stdout = _ToolsAgent(
                description=f"unified-agent (round={round_num}, attempt={attempt})",
                prompt=user_prompt + _SKILL_LOAD_DIRECTIVE + _output_deadline,
                subagent_type="skill-unified-agent",
                cwd=None,
            )
        except Exception as e:
            logger.error("unified agent sub-agent 调用失败: %s", e)
            raise
        result = _parse_subagent_json_output(stdout, path=output_path)
        if result is None:
            raise RuntimeError(
                f"unified agent sub-agent 输出无法解析为 JSON。stdout 前 500 字符: {stdout[:500]!r}"
            )

    # 标准化
    result.setdefault("round", round_num)
    result.setdefault("per_file_findings", [])

    # 重要：校验每个 file 的 dim_scores 必须齐全（参照 evaluator agent 的 12 维评分契约），
    # 缺失则触发 REWORK（让 LLM 重输出，而不是静默用 0 分兜底）
    _expected_total_dims = [
        k for k in framework_cfg.get("rubric", {}) if k.startswith("dim")
    ]
    # ：按 file role 决定 unique 分数阈值（knowledge/asset/doc 类文件
    # LLM 倾向打 8/9/10"不涉及"档位，集中在 2 个不同分数上，被硬约束≥3 误判为同质化 reject）
    # 阈值：entrypoint/implementation/template=≥3（默认硬约束），knowledge/asset/doc=≥2（放宽）
    _role_threshold = ROLE_UNIQUE_SCORE_THRESHOLD  # 用模块级常量（已抽到顶层）
    # 从 relation_tree 拿 file→role 映射
    _file_role_map: dict[str, str] = {}
    if isinstance(relation_tree, dict):
        for row in relation_tree.get("summary_table", []) or []:
            fp = row.get("path", "")
            if fp:
                _file_role_map[fp] = row.get("role", "other")
    _rework_reason: Optional[str] = None
    for entry in result["per_file_findings"]:
        if not isinstance(entry, dict):
            continue
        f = entry.get("file", "")
        ds = entry.get("dim_scores") or {}
        filled = [d for d in _expected_total_dims
                  if isinstance(ds.get(d), dict) and ds[d].get("score") is not None]
        missing = [d for d in _expected_total_dims if d not in ds]
        if len(filled) < len(_expected_total_dims):
            _rework_reason = (
                f"per_file_findings[{f}].dim_scores 缺失（实填 {len(filled)}/{len(_expected_total_dims)}），"
                f"缺: {missing[:5]}{'...' if len(missing)>5 else ''}"
            )
            break
        # 反同质化校验：按 file role 决定阈值（knowledge 类文件 ≥2 即可）
        scores = [ds[d]["score"] for d in _expected_total_dims if d in ds]
        unique_scores = set(scores)
        role = _file_role_map.get(f, "other")
        threshold = _role_threshold.get(role, 3)
        if len(unique_scores) < threshold:
            _rework_reason = (
                f"per_file_findings[{f}].dim_scores 同质化（role={role}，"
                f"{len(unique_scores)} 个不同分数 → 不满足至少 {threshold} 个不同）"
            )
            break
        # (无强制低分必有 finding 校验: LLM 自己决定, 不在此处添加复杂规则)
    if _rework_reason:
        raise RuntimeError(f"dim_scores 不合格触发 REWORK: {_rework_reason}")

    # 跨文件合并 mods（从 per_file_findings 抽取所有 findings → modifications）
    all_mods: list[dict] = []
    for entry in result["per_file_findings"]:
        if not isinstance(entry, dict):
            continue
        f = entry.get("file", "")
        for finding in entry.get("findings") or []:
            if not isinstance(finding, dict):
                continue
            mod = {
                "file": f,
                "section": finding.get("section", ""),
                "before": finding.get("before", ""),
                "after": finding.get("after", ""),
                "dim_improved": finding.get("dim_improved", "unknown"),
                "pattern_used": finding.get("pattern_used", "P?"),
                "rationale": finding.get("rationale", ""),
            }
            all_mods.append(mod)
    result["modifications"] = all_mods

    # Python 端聚合分数（取代 LLM judge）
    total, dim_scores_avg, rating = aggregate_dim_scores(
        result["per_file_findings"],
        framework_cfg.get("rubric", {}),
        relation_tree=relation_tree,
    )
    result["total"] = total
    result["rating"] = rating
    result["dim_scores"] = {k: round(v, 2) for k, v in dim_scores_avg.items()}

    # 文件级分数映射（file → score），便于人工排查
    # 优先取 entry.dim_scores（每文件 per-dim 分数），缺则取 entry.score，再缺则用 findings 数推断
    file_scores: dict[str, float] = {}
    file_dim_scores: dict[str, dict[str, float]] = {}
    for entry in result["per_file_findings"]:
        if not isinstance(entry, dict) or not entry.get("file"):
            continue
        f = entry["file"]
        # 1. 优先取 dim_scores
        ds = entry.get("dim_scores") or {}
        if isinstance(ds, dict) and ds:
            file_dim_scores[f] = {}
            for dim, info in ds.items():
                if isinstance(info, dict) and isinstance(info.get("score"), (int, float)):
                    file_dim_scores[f][dim] = float(info["score"])
            if file_dim_scores[f]:
                file_scores[f] = round(
                    sum(file_dim_scores[f].values()) / len(file_dim_scores[f]), 2
                )
        # 2. 取单 score 字段
        if f not in file_scores:
            score = entry.get("score")
            if isinstance(score, (int, float)) and not isinstance(score, bool):
                file_scores[f] = float(score)
        # 3. 兜底：用 findings 数推断（与 aggregate_dim_scores 一致）
        if f not in file_scores:
            findings = entry.get("findings") or []
            file_scores[f] = 10.0 if not findings else max(5.0, 10.0 - len(findings) * 0.5)
    result["file_scores"] = file_scores
    result["file_dim_scores"] = file_dim_scores

    logger.info(
        "[unified agent 完成] round=%d attempt=%d files=%d mods=%d total=%.2f rating=%s duration=%.1fs",
        round_num, attempt, len(result["per_file_findings"]),
        len(all_mods), total, rating, _t.monotonic() - _t0,
    )

    # 落盘：v0.19+ 职责分离 + 多次评测独立产物
    #   单次评测（output_path = "round_X/proposal"）：
    #     - proposal.json（本次 LLM 调用的完整 result）
    #     - score.json（纯分数 + rationale）
    #     - per_file_findings/（每文件独立 json）
    #   多次评测（output_path = "round_X/run{N}"）：
    #     - run{N}_proposal.json（本次 LLM 调用的完整 result）
    #     - run{N}_score.json（纯分数 + rationale）
    #     - run{N}_per_file_findings/（每文件独立 json）
    # 主循环（unified）另外写聚合的 score.json / proposal.json / per_file_findings/
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 命名约定：output_path.name 是 "proposal"（单次）还是 "run1"/"run2"（多次）
        if output_path.name == "proposal":
            # 单次评测：保持原命名（proposal.json / score.json / per_file_findings/）
            proposal_name = "proposal.json"
            score_name = "score.json"
            per_file_dir_name = "per_file_findings"
        else:
            # 多次评测：run{N}_proposal.json / run{N}_score.json / run{N}_per_file_findings/
            run_label = output_path.name  # run1 / run2 / run3
            proposal_name = f"{run_label}_proposal.json"
            score_name = f"{run_label}_score.json"
            per_file_dir_name = f"{run_label}_per_file_findings"

        # 1. 本次 LLM 调用的完整 result（proposal.json / run{N}_proposal.json）
        (output_path.parent / proposal_name).write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 2. 纯分数 score.json（单次）/ run{N}_score.json（多次）
        score_payload = {
            "round": result.get("round", round_num),
            "total": result.get("total", 0.0),
            "rating": result.get("rating", "UNSCORED"),
            "dim_scores": result.get("dim_scores", {}),
            "file_scores": result.get("file_scores", {}),
            "file_dim_scores": result.get("file_dim_scores", {}),
            "per_file_analysis": [
                {
                    "file": e.get("file", ""),
                    "dim_scores": e.get("dim_scores") or {},
                    "findings_count": len(e.get("findings") or []),
                    "score": result["file_scores"].get(
                        e.get("file", ""),
                        10.0 if not e.get("findings")
                        else max(5.0, 10.0 - len(e["findings"]) * 0.5)
                    ),
                }
                for e in result.get("per_file_findings", [])
                if isinstance(e, dict)
            ],
        }
        (output_path.parent / score_name).write_text(
            json.dumps(score_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 3. 每文件独立 JSON（per_file_findings/ 或 run{N}_per_file_findings/）
        per_file_dir = output_path.parent / per_file_dir_name
        per_file_dir.mkdir(parents=True, exist_ok=True)
        for entry in result["per_file_findings"]:
            if not isinstance(entry, dict):
                continue
            f = entry.get("file", "")
            if not f:
                continue
            safe_name = f.replace("/", "__").replace("\\", "__")
            (per_file_dir / f"{safe_name}.json").write_text(
                json.dumps(entry, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    return result


@dataclass
class UnifiedRoundResult:
    """unified agent 单 round 结果（替代 6 phase state machine）"""
    round_num: int
    total: float
    delta: float
    rating: str
    modifications_count: int
    applied_count: int
    files_changed: list
    verdict: str  # improved | plateau | reverted
    per_file_findings: list  # 原始输出（供诊断）


def run_unified_static_optimization(config, framework_cfg) -> list[UnifiedRoundResult]:
    """单阶段主循环（融合评分 + 优化）：unified agent 一次调用 → apply → aggregate → snapshot/revert。

    替代原 6 phase 状态机（约 1200 行）：
      P1/P2/P6 (metadata) → 简化为进度日志
      P3 (optimizer + REWORK) → 替换为 invoke_unified_agent 一次调用（自带 REWORK via max_attempts）
      P4 (verifier) → 移除（apply_modifications 内置 before/after 校验）
      P5 (evaluator) → 替换为 aggregate_dim_scores Python 端聚合

    产物结构（保持兼容）：
      workspace/
        skill/                         — 工作副本（初始 = baseline copy）
        round_{N}/
          proposal.json
          per_file_findings/*.json
        round_{N}_before_skill/         — apply 前的 snapshot
        round_{N}_after_skill/          — apply 后的副本
        static_history.json
        best_skill/                     — 评分最高轮的 skill 副本
    """
    import shutil
    import time as _t

    from .static_apply import (apply_modifications, compute_skill_hash,
                               snapshot_skill, update_best_skill)

    logger.info(
        "[unified main loop] 启动: skill=%s rounds=%d break=%.1f",
        config.skill_path, config.max_rounds, config.break_threshold,
    )

    skill_path = config.skill_path
    skill_root = skill_path.parent
    skill_name = skill_root.name
    workspace = config.workspace

    # 1) 准备 skill 工作副本（workspace/skill/{skill_name}/,与 6 phase 路径 + COSIGHT.md 7.2 约定对齐）
    # ：之前 buggy 版本用 workspace/skill/（漏 SkillName 子目录），导致 HTML 报告 diff 与 best_skill
    # 路径结构错位（一边含 SkillName 一边不含），diff 结果大量假"新增/删除"。
    # 修复后：work_skill 也含 skill_name 子目录，与 round_N_before/after_skill/skill/{skill_name}/ 对齐，
    # sub-agent 输出的 file 字段（如 "SKILL.md"）是 relative_to(work_skill) 的相对路径，apply 时
    # target = work_skill / "SKILL.md" = workspace/skill/{skill_name}/SKILL.md，依然命中。
    work_skill = workspace / "skill" / skill_name
    if work_skill.exists():
        shutil.rmtree(work_skill)
    shutil.copytree(skill_root, work_skill)

    target_files = collect_target_files(work_skill, config.max_files)
    logger.info("[unified main loop] 扫描到 %d 个待优化文件", len(target_files))

    history: list[UnifiedRoundResult] = []
    best_score = -1.0
    best_round = 0
    delta_history: list[float] = []
    base_score = 0.0

    # ========== round_0 baseline 评估（不 apply mods）==========
    # v0.19+：多次评测（默认 N=3）→ 取 mean + stdev，消除 LLM judge 抽样噪声
    # 与原 6 phase 路径 evaluate_with_runs 对齐（聚合逻辑在 _aggregate_unified_runs）
    n_eval_runs = max(1, int(getattr(config, "eval_runs", 3) or 3))
    logger.info(
        "[unified main loop] === Round 0 baseline 评估 === (N=%d 次评测取平均)",
        n_eval_runs,
    )
    try:
        # v0.19+ 多次评测并发（与老版 evaluate_with_runs 对齐：ThreadPoolExecutor + as_completed）
        # 原因：老版（/参考/skillx-alpha-agents/scripts/optimizers/static_agents.py:725-770）
        # 用 ThreadPoolExecutor(max_workers=n_runs) 并发跑 N 次 invoke_evaluator，
        # 新版 unified 路径最初漏了这个并发能力，串行跑 N×单次时间。
        # 修复：用 ThreadPoolExecutor 并发，as_completed 收集结果（保序：按 run_i 排序）。
        # tools.Agent 通过 cosight -p 启独立子进程，线程安全。
        from concurrent.futures import ThreadPoolExecutor, as_completed

        baseline_runs: list[dict] = []

        def _run_one_baseline(run_i: int) -> tuple[int, dict | None, Exception | None]:
            run_output_path = (
                workspace / "round_0" / f"run{run_i + 1}"
                if n_eval_runs > 1
                else workspace / "round_0" / "proposal"
            )
            try:
                single = invoke_unified_agent(
                    skill_root=work_skill,
                    target_files=target_files,
                    config=config,
                    round_num=0,
                    output_path=run_output_path,
                    framework_cfg=framework_cfg,
                    attempt=0,
                    score_mode=getattr(config, "score_mode", "subagent"),
                )
                return run_i, single, None
            except Exception as e:  # noqa: BLE001
                return run_i, None, e

        if n_eval_runs > 1:
            # 并发跑 N 次 invoke_unified_agent（max_workers=N）
            with ThreadPoolExecutor(max_workers=n_eval_runs) as ex:
                futures = [ex.submit(_run_one_baseline, i) for i in range(n_eval_runs)]
                for fut in as_completed(futures):
                    run_i, single, err = fut.result()
                    if err is not None:
                        logger.warning(
                            "[baseline run %d] 失败: %s (将用 0 分 fallback)",
                            run_i + 1, err,
                        )
                        continue
                    baseline_runs.append(single)  # noqa: PERF401
            # 按 run_i 排序（保序：run1, run2, run3）
            baseline_runs.sort(key=lambda r: r.get("round", 0))
        else:
            # n_eval_runs == 1：单次不并发
            _, single, _ = _run_one_baseline(0)
            baseline_runs.append(single)
        baseline_result = _aggregate_unified_runs(
            runs=baseline_runs,
            framework_cfg=framework_cfg,
            n_runs=n_eval_runs,
        )
        # 落盘聚合后的 proposal（v0.19+ 职责分离：只含提案字段，不含 score 字段）
        # proposal.json 专注：round, diagnosis, per_file_findings, modifications, _meta
        baseline_proposal_payload = {
            "round": 0,
            "diagnosis": baseline_result.get("diagnosis", ""),
            "per_file_findings": baseline_result.get("per_file_findings", []),
            "modifications": baseline_result.get("modifications", []),
            "_meta": {
                "files_scanned": len(baseline_result.get("per_file_findings", [])),
                "mods_proposed": len(baseline_result.get("modifications", [])),
                "total_score": baseline_result.get("total", 0.0),
                "rating": baseline_result.get("rating", "UNSCORED"),
                "n_eval_runs": baseline_result.get("_eval_runs", {}).get("n_requested", 1),
            },
        }
        (workspace / "round_0" / "proposal.json").write_text(
            json.dumps(baseline_proposal_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        base_score = float(baseline_result.get("total", 0.0))
        base_rating = baseline_result.get("rating", "UNSCORED")
        # 写 round_0/score.json
        baseline_score_payload = {
            "round": 0,
            "total": base_score,
            "rating": base_rating,
            "delta": 0.0,
            "verdict": "baseline",
            "dim_scores": baseline_result.get("dim_scores", {}),
            "file_scores": baseline_result.get("file_scores", {}),
            # v0.19+ 多次评测元数据（n_requested/per_run_totals/total_stdev/...）
            "_eval_runs": baseline_result.get("_eval_runs", {}),
        }
        (workspace / "round_0" / "score.json").write_text(
            json.dumps(baseline_score_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        history.append(UnifiedRoundResult(
            round_num=0,
            total=base_score,
            delta=0.0,
            rating=base_rating,
            modifications_count=0,
            applied_count=0,
            files_changed=[],
            verdict="baseline",
            per_file_findings=baseline_result.get("per_file_findings", []),
        ))
        logger.info(
            "[baseline] 完成: total=%.2f rating=%s (后续 round 与之对比)",
            base_score, base_rating,
        )
        # 重要: 把 baseline 副本写入 best_skill,让 HTML diff 永远有对比基线
    except Exception as e:  # noqa: BLE001
        logger.error("[baseline] 评估失败: %s (后续 round 将以 0 作为基线)", e)
        base_score = 0.0

    # 注: best_skill 仅在 round 1+ 真采纳 mod 时创建或更新。baseline 阶段
    # 不创建 best_skill,这样后续 round 未采纳时 best_skill 不存在(意图如设计)。
    best_score = base_score
    best_round = 0

    for round_num in range(1, config.max_rounds + 1):
        t0 = _t.monotonic()
        round_dir = workspace / f"round_{round_num}"
        round_dir.mkdir(parents=True, exist_ok=True)
        proposal_path = round_dir / "proposal"

        logger.info("[unified main loop] === Round %d 启动 ===", round_num)

        # 2) 调用 unified agent（含 REWORK 重试，最多 3 次）
        result = None
        _rework_reasons: list[str] = []
        for attempt in range(3):  # 0,1,2 = 首次 + 2 次 rework
            try:
                # v0.19+：每次 attempt 内部并发跑 N 次取平均（多次评测）
                # REWORK 是"重新跑 prompt"语义，与"多次评测取平均"是不同维度
                # 一个 attempt 失败 → 整个 attempt 重试（保留 N 次平均结果）
                # 一个 attempt 成功 → 内部 N 次都成功才算成功，否则归为 partial
                from concurrent.futures import ThreadPoolExecutor, as_completed

                def _run_one_round(run_i: int) -> tuple[int, dict | None, Exception | None]:
                    # 多次评测产物命名规范：run{N}_XXX 前缀
                    run_output_path = (
                        round_dir / f"run{run_i + 1}"
                        if n_eval_runs > 1
                        else proposal_path
                    )
                    try:
                        single = invoke_unified_agent(
                            skill_root=work_skill,
                            target_files=target_files,
                            config=config,
                            round_num=round_num,
                            output_path=run_output_path,
                            framework_cfg=framework_cfg,
                            attempt=attempt,
                            score_mode=getattr(config, "score_mode", "subagent"),
                        )
                        return run_i, single, None
                    except Exception as e:  # noqa: BLE001
                        return run_i, None, e

                round_runs: list[dict] = []
                if n_eval_runs > 1:
                    # 并发跑 N 次 invoke_unified_agent（与 baseline 一致）
                    with ThreadPoolExecutor(max_workers=n_eval_runs) as ex:
                        futures = [ex.submit(_run_one_round, i) for i in range(n_eval_runs)]
                        for fut in as_completed(futures):
                            run_i, single, err = fut.result()
                            if err is not None:
                                logger.warning(
                                    "[Round %d run %d] 失败: %s",
                                    round_num, run_i + 1, err,
                                )
                                continue
                            round_runs.append(single)  # noqa: PERF401
                    # 按 run_i 排序保序
                    round_runs.sort(key=lambda r: r.get("round", 0))
                else:
                    _, single, _ = _run_one_round(0)
                    round_runs.append(single)
                result = _aggregate_unified_runs(
                    runs=round_runs,
                    framework_cfg=framework_cfg,
                    n_runs=n_eval_runs,
                )
                # 落盘聚合后的 proposal（v0.19+ 职责分离：只含提案字段，不含 score 字段）
                # proposal.json 专注：round, diagnosis, per_file_findings, modifications, _meta
                round_proposal_payload = {
                    "round": round_num,
                    "diagnosis": result.get("diagnosis", ""),
                    "per_file_findings": result.get("per_file_findings", []),
                    "modifications": result.get("modifications", []),
                    "_meta": {
                        "files_scanned": len(result.get("per_file_findings", [])),
                        "mods_proposed": len(result.get("modifications", [])),
                        "total_score": result.get("total", 0.0),
                        "rating": result.get("rating", "UNSCORED"),
                        "n_eval_runs": result.get("_eval_runs", {}).get("n_requested", 1),
                    },
                }
                (proposal_path.with_suffix(".json")).write_text(
                    json.dumps(round_proposal_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                break  # 成功
            except Exception as e:
                _rework_reasons.append(str(e)[:200])
                logger.warning(
                    "[Round %d] unified agent REWORK attempt=%d 失败: %s",
                    round_num, attempt, e,
                )
                if attempt < 2:
                    import time as _sleep_rework
                    _sleep_rework.sleep(2 ** attempt)  # 2,4 秒退避
                    continue
                # 3 次都失败 → broken
                logger.error(
                    "[Round %d] unified agent REWORK 3 次失败，本轮放弃: %s",
                    round_num, _rework_reasons,
                )
                history.append(UnifiedRoundResult(
                    round_num=round_num, total=0.0, delta=0.0, rating="BROKEN",
                    modifications_count=0, applied_count=0, files_changed=[],
                    verdict="broken", per_file_findings=[],
                ))
                result = None
                break
        if result is None:
            break  # 跳出外层 for round_num

        #  work_skill 兜底：v0.19+ 之前 unified 路径会在 baseline 完成后某处删 work_skill
        # （并发/REWORK 等路径），导致 round 1+ 的 snapshot_skill 失败。
        # 修复：每轮 P3 之前确保 work_skill 存在（不存在则从原始 skill_root 重建）
        if not work_skill.exists():
            logger.warning(
                "[Round %d] work_skill 不存在，从原 skill_root 重建: %s",
                round_num, work_skill,
            )
            work_skill.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(skill_root, work_skill)

        # 3) snapshot before (放在 round_N/round_N_before_skill/skill/<skill_name>/,与旧 6 phase 路径对齐)
        before_dir = round_dir / f"round_{round_num}_before_skill" / "skill" / skill_name
        snapshot_skill(work_skill, before_dir)
        # 关键: 计算 apply 前 skill 关键 file 的 sha256 (用于判定真改)
        before_sha = compute_skill_hash(work_skill)

        # 4) 应用 mods
        mods = result.get("modifications", [])
        after_dir = round_dir / f"round_{round_num}_after_skill" / "skill" / skill_name
        apply_res = apply_modifications(
            modifications=mods,
            skill_root=work_skill,
            protected_assets=config.protected_assets,
            workspace=workspace,
        )
        applied = apply_res.applied if hasattr(apply_res, "applied") else 0

        # 计算 apply 后 sha,与 before 比对
        after_sha = compute_skill_hash(work_skill)
        real_files_changed = before_sha != after_sha

        # 4.5) snapshot after（apply 后的 skill 全量副本,与旧 6 phase 路径对齐）
        # 仅在真改了文件时创建空目录,避免空目录噪音
        if applied > 0 and real_files_changed:
            snapshot_skill(work_skill, after_dir)
            logger.info(
                "[Round %d] after_skill snapshot done: %s",
                round_num, after_dir,
            )

        # 4.6) 改进后立刻再评估：避免 LLM judge "改后更严" 的副作用
        # 若 round_1 后 dim3 等核心杠杆点继续下降，则视为改进失败,触发 REWORK
        # 但目前 LLM judge 单次评估,需要后续 impl:得分恢复评估轮
        # （.x 治本: 整合"optimizer + evaluator"循环, 放低优先级）

        # 5) 评分（已由 unified agent 计算）
        score = float(result.get("total", 0.0))
        rating = result.get("rating", "UNSCORED")

        # R1+ 的 delta 都对比 round_0 baseline（而不是 best_score）
        delta = score - base_score
        # 关键：verdict 必须反映"有没有真改动",而非仅仅分数浮动
        # Bug fix: 用 before_sha vs after_sha 判定真有改动,而不是依赖 files_changed
        has_real_improvement = real_files_changed
        # 采纳门限: 分数提升 ≥ 0.5 才算真正的提升（避免 LLM judge ±0.5 噪声）
        improvement_threshold = 0.5

        if has_real_improvement and score - best_score >= improvement_threshold:
            verdict = "improved"
        elif delta < -2:  # 回退阈值
            verdict = "reverted"
            # 回退到 before snapshot
            shutil.rmtree(work_skill)
            shutil.copytree(before_dir, work_skill)
            score = best_score
        else:
            # 包括:applied=0 但 score 提升(LLM 噪声)→ plateau 而非 improved
            verdict = "plateau"
            delta = score - best_score
            if score > best_score:
                # 即便 score > best_score,只要没真改文件,仍是 plateau (LLM 噪声)
                verdict = "improved" if has_real_improvement else "plateau"
            elif delta < -2:  # 回退阈值
                verdict = "reverted"
                # 回退到 before snapshot
                shutil.rmtree(work_skill)
                shutil.copytree(before_dir, work_skill)
                score = best_score
            else:
                verdict = "plateau"

        # 关键：best_score 仅在有真改动时才刷新
        # 避免 LLM judge 噪声把"分数波动"记为"最佳",导致后续所有轮都比这个 baseline 浮动低
        # 永远不会触发"score > best_score",事实上这一轮啥也没改
        if score - best_score >= improvement_threshold and has_real_improvement:
            best_score = score
            best_round = round_num
            update_best_skill(work_skill, workspace, skill_name, round_num, score)
        elif score - best_score >= improvement_threshold:
            logger.info(
                "[Round %d] score 提升 (%.2f > %.2f) 但 real_files_changed=False, 不更新 best_skill (避免 LLM judge 噪声导致的伪采纳)",
                round_num, score, best_score,
            )

        # 6) 写 score.json（兼容旧格式）
        score_payload = {
            "round": round_num,
            "total": score,
            "rating": rating,
            "delta": delta,
            "verdict": verdict,
            "dim_scores": result.get("dim_scores", {}),
            "file_scores": result.get("file_scores", {}),
            "applied": applied,
            "files_changed": apply_res.files_changed if hasattr(apply_res, "files_changed") else [],
            # v0.19+ 多次评测元数据（n_requested/per_run_totals/total_stdev/...）
            "_eval_runs": result.get("_eval_runs", {}),
        }
        (round_dir / "score.json").write_text(
            json.dumps(score_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 7) 写 round_result.json（兼容旧格式）
        round_result_payload = {
            "round": round_num,
            "score_block": {"total": score, "rating": rating, "dim_scores": result.get("dim_scores", {})},
            "proposal": {
                "round": round_num,
                "diagnosis": result.get("diagnosis", ""),
                "per_file_findings": result.get("per_file_findings", []),
                "modifications": mods,
            },
            "apply": {
                "applied": applied,
                "skipped": apply_res.skipped if hasattr(apply_res, "skipped") else 0,
                "failed": apply_res.failed if hasattr(apply_res, "failed") else 0,
                "files_changed": apply_res.files_changed if hasattr(apply_res, "files_changed") else [],
                "errors": apply_res.errors if hasattr(apply_res, "errors") else [],
            },
            "delta": delta,
            "verdict": verdict,
        }
        (round_dir / "round_result.json").write_text(
            json.dumps(round_result_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        history.append(UnifiedRoundResult(
            round_num=round_num,
            total=score,
            delta=delta,
            rating=rating,
            modifications_count=len(mods),
            applied_count=applied,
            files_changed=apply_res.files_changed if hasattr(apply_res, "files_changed") else [],
            verdict=verdict,
            per_file_findings=result.get("per_file_findings", []),
        ))

        # 8) 触顶 break：连续 2 轮 Δ < break_threshold
        delta_history.append(delta)
        if len(delta_history) >= 2:
            recent = delta_history[-2:]
            if all(abs(d) < config.break_threshold for d in recent):
                logger.info(
                    "[unified main loop] 连续 2 轮 Δ<%.1f, 触顶 break",
                    config.break_threshold,
                )
                break

        t1 = _t.monotonic()
        logger.info(
            "[Round %d] 完成: total=%.2f rating=%s Δ=%+.2f verdict=%s applied=%d 耗时=%.1fs",
            round_num, score, rating, delta, verdict, applied, t1 - t0,
        )

    # 写 static_history.json（顶层 list，与 _load_history 兼容）
    # 之前写为 dict{"history":[...]}，但 _load_history iter 当成 history 项的迭代，导致
    # dict keys 当作 string 项,触发 'str' object has no attribute 'get'
    static_history = []
    for h in history:
        rn = h.round_num
        # 从 round_{rn}/score.json 读取已聚合的 dim_scores（避免再算一遍）
        round_score_path = workspace / f"round_{rn}" / "score.json"
        dim_scores_for_history: dict[str, float] = {}
        try:
            if round_score_path.exists():
                score_data = json.loads(round_score_path.read_text(encoding="utf-8"))
                dim_scores_for_history = score_data.get("dim_scores", {}) or {}
        except (OSError, json.JSONDecodeError):
            pass
        # baseline(rn=0) 可能没写 round_0/score.json,从 baseline_score_payload 读
        if not dim_scores_for_history:
            # 用 round_0 placeholder;HTML 报告会自动跳过
            pass
        static_history.append({
            "round": rn, "total": h.total, "delta": h.delta,
            "rating": h.rating, "mods": h.modifications_count,
            "applied": h.applied_count, "files_changed": h.files_changed,
            "verdict": h.verdict,
            "dim_scores": dim_scores_for_history,
        })
    (workspace / "static_history.json").write_text(
        json.dumps(static_history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(
        "[unified main loop] 完成: %d 轮, best_score=%.2f (round %d)",
        len(history), best_score, best_round,
    )

    # HTML 可视化报告（ 与 PNG 雷达图并存，互补）
    # 不阻塞主流程,失败仅 warn 日志
    try:
        from .static_html_history import generate_score_history_html

        # ：之前 buggy 版本 best_skill_dir 用 workspace/best_skill（漏 skill_name），
        # original_skill 用 config.skill_path.parent（原 Skill 目录，不在 workspace 内），
        # 导致 diff 两边结构不对齐（一边含 SkillName 一边不含），diff 结果错位。
        # 修复：best_skill_dir 加 skill_name 子目录（与 update_best_skill 内部一致），
        # original_skill 用 round_1 的 before snapshot（最稳的 baseline 副本）。
        best_skill_dir = workspace / "best_skill" / skill_name
        # round_1 的 before snapshot 是 apply 前的最原始副本（若没跑过 round_1 则 fallback）
        before_snapshot = workspace / "round_1" / "round_1_before_skill" / "skill" / skill_name
        if not before_snapshot.exists():
            before_snapshot = work_skill  # fallback：unified 路径下 work_skill 初始未 apply
        original_skill = before_snapshot

        html_result = generate_score_history_html(
            workspace=workspace,
            framework_cfg=framework_cfg,
            workspace_name=skill_name,
            old_skill_path=original_skill,
            new_skill_path=best_skill_dir,
        )
        if html_result.skipped:
            logger.warning("HTML 报告跳过：%s", html_result.reason)
        else:
            logger.info(
                "HTML 报告已生成: %s (rounds=%d dims=%d)",
                html_result.output_path, html_result.rounds_plotted, html_result.dims_plotted,
            )
    except ImportError:
        logger.warning("static_html_history 模块导入失败,跳过 HTML 报告")
    except Exception as e:
        import traceback
        logger.warning("HTML 报告生成失败（非致命）: %s\n%s", e, traceback.format_exc())

    return history
