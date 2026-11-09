"""
Workflow Pipeline Executor — 业务方完整评测管道接入
====================================================
从 config.json["pipeline"] 字段读取业务方管道配置，在 orchestrator 每轮迭代中执行完整管道。

隔离策略：
- 在业务方评测目录原地执行（inline 模式）
- data/ 全清：每次评测前/后通过 clean_eval_data_sandbox 全清
- 业务方评测管线自行重建其测试数据
- 评测完成后将沙箱内有用数据归档到 workspace/round_{N}/

分数来源：不再在此处提取。由 ScoreAnalyzerAgent 扫描归档产物独立评分。

加载链：orchestrator 从 CLI/env 派生配置 → 写入 config.json["pipeline"] →
populate_pipeline_in_config 补 cleanup/cmd 注入 → 工厂从 args.pipeline_config_dict 取出 →
本模块直接消费 dict，不再读 yaml。
"""

import atexit
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

# 添加父目录到路径
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from base import BaseEvaluator, EvaluationError, EvaluationResult
from orchestrators.workspace import clean_eval_data_sandbox


def _load_eval_model_config() -> Dict[str, str]:
    """从 `config/evolve-user-config.yaml` 的 `eval_model` 段读取评测模型配置(单点)。

    返回 {name, base_url, api_key};未配置返回空 dict(调用方不覆盖,评测继承环境)。
    模型变化只改 YAML 的 eval_model 段一处,不波及代码 —— 避免硬编码模型名/端口,
    也避免评测 judge 继承教师模型(如 M3)导致配额耗尽(429)。
    api_key 用于 ccr/本地 router 场景:评测 cosight 必须携带该 router 自己的 key,
    否则继承全局 ANTHROPIC_AUTH_TOKEN(教师模型 key)会被 router 以 401 拒绝。
    """
    try:
        import yaml as _yaml
        _cfg_file = Path(__file__).resolve().parent.parent.parent / "config" / "evolve-user-config.yaml"
        if not _cfg_file.exists():
            return {}
        with open(_cfg_file, "r", encoding="utf-8") as _f:
            _cfg = _yaml.safe_load(_f) or {}
        _em = (_cfg.get("eval_model") or {}) or {}
        return {
            "name": str(_em.get("name", "")).strip(),
            "base_url": str(_em.get("base_url", "")).strip(),
            "api_key": str(_em.get("api_key", "")).strip(),
        }
    except Exception:
        return {}

# ── eval 子进程解耦：detached Popen + 安静轮询 ────────────────
# 根因：原 _run_script_step_inline 用 communicate() 同步阻塞，主流程被长 eval-cmd 卡死。
# 方案：start_new_session=True 创建新进程组（PID==PGID），stdout/stderr 重定向到日志文件，
#      主流程用 proc.poll() 轮询退出；超时/异常通过进程组级 killpg 清理子子孙孙；
#      atexit 兜底优雅退出场景（orchestrator 任何 sys.exit 路径都触发）。
# 边界：本模块只关心进程生命周期与日志，不引入产物 sentinel / manifest / 并发框架。

_ACTIVE_EVAL_PGIDS: Set[int] = set()


def _terminate_process_group(pgid: int, grace_seconds: int = 60) -> None:
    """进程组级清理：SIGTERM → grace → SIGKILL。killpg 失败静默（进程已死/无权限）。"""
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        return
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except (OSError, ProcessLookupError):
            return
        time.sleep(1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass


def _kill_active_eval_groups() -> None:
    """atexit hook：orchestrator 任何路径退出时清理残留 eval 进程组。"""
    pgids = list(_ACTIVE_EVAL_PGIDS)
    _ACTIVE_EVAL_PGIDS.clear()
    for pgid in pgids:
        _terminate_process_group(pgid, grace_seconds=10)


atexit.register(_kill_active_eval_groups)


def _run_step_with_poll(
    cmd: Union[str, List[str]],
    cwd: Union[str, Path],
    env: Dict[str, str],
    log_path: Path,
    step_timeout: Optional[int],
    step_name: str,
    poll_interval: float = 5.0,
    grace_seconds: int = 60,
) -> Dict[str, Any]:
    """detached Popen + 安静轮询。

    返回: {status, returncode, log_path, elapsed, timed_out, pid, pgid}。
    - str cmd → shell=True；List[str] cmd → 直接 exec（cosight_command 形式）。
    - start_new_session=True 把子进程置为新进程组组长，os.killpg 即可清理整棵子树。
    - step_timeout=None/0 表示无超时（与 v2.8 修复对齐：cosight -p 默认 36000s）。
    - 超时：SIGTERM 进程组 → grace_seconds 后 SIGKILL。
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = time.monotonic()
    timed_out = False
    returncode: Optional[int] = None
    pid: Optional[int] = None
    pgid: Optional[int] = None

    with open(log_path, "w", encoding="utf-8", buffering=1) as log_f:
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(cwd), env=env,
                shell=isinstance(cmd, str),
                stdout=log_f, stderr=subprocess.STDOUT,
                text=True, start_new_session=True,
            )
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "returncode": None, "log_path": str(log_path),
                    "elapsed": 0.0, "timed_out": False, "pid": None, "pgid": None,
                    "error": str(exc)}

        pid = proc.pid
        try:
            pgid = os.getpgid(pid)
        except OSError:
            pgid = pid  # 子进程已退出罕见 race
        _ACTIVE_EVAL_PGIDS.add(pgid)

        try:
            deadline = (started_at + step_timeout) if step_timeout else None
            while True:
                ret = proc.poll()
                if ret is not None:
                    returncode = ret
                    break
                time.sleep(poll_interval)
                if deadline and time.monotonic() >= deadline:
                    timed_out = True
                    _terminate_process_group(pgid, grace_seconds=grace_seconds)
                    returncode = proc.poll() if proc.poll() is not None else -1
                    break
        finally:
            # 分两路径：
            # - 直接子进程能 reap（正常退出 / 超时已 kill）→ 组已死，安全 discard
            # - 直接子进程 5s 内未死（异常情况：SIGINT 等）→ atexit 安全网兜底
            try:
                proc.wait(timeout=5)
                _ACTIVE_EVAL_PGIDS.discard(pgid)
            except subprocess.TimeoutExpired:
                _terminate_process_group(pgid, grace_seconds=5)

    elapsed = time.monotonic() - started_at
    status = "ok" if (returncode == 0 and not timed_out) else "error"
    return {"status": status, "returncode": returncode, "log_path": str(log_path),
            "elapsed": elapsed, "timed_out": timed_out, "pid": pid, "pgid": pgid}


class WorkflowPipelineConfig:
    """管道配置解析（YAML/JSON）"""

    def __init__(self, config: Dict[str, Any]):
        pipeline = config.get("pipeline", config)
        self.base_dir = Path(pipeline["base_dir"]).resolve()
        self.activities = pipeline.get("activities", [])
        if not self.activities:
            top_activities = config.get("activities", {})
            if isinstance(top_activities, dict):
                default = top_activities.get("default", "")
                if default:
                    self.activities = [default]
            elif isinstance(top_activities, list) and top_activities:
                self.activities = [str(top_activities[0])]
        self.timeout = int(pipeline.get("timeout", 10800))

        self.sandbox_name = pipeline.get("sandbox_name", self.base_dir.name)
        self.steps = pipeline.get("steps", [])

        # 直接从 user-config.yaml 读取 list（paths.need_cleaned_dir），避免 env join/split
        # need_cleaned_dir 是"需要清理的目录"列表，清理时检查存在性（存在则清内容，不存在则跳过），
        # 不在初始化阶段创建目录
        from orchestrators.workspace import (USER_CONFIG_PATH,
                                             get_need_cleaned_dirs)
        try:
            self.need_cleaned_dirs = get_need_cleaned_dirs()
        except Exception as e:
            raise ValueError(
                f"读取 paths.need_cleaned_dir 失败: {type(e).__name__}: {e} | "
                f"config_path={USER_CONFIG_PATH} | exists={USER_CONFIG_PATH.exists()}"
            ) from e
        if not self.need_cleaned_dirs:
            raise ValueError(
                f"paths.need_cleaned_dir 配置为空 | config_path={USER_CONFIG_PATH} | "
                f"exists={USER_CONFIG_PATH.exists()} | 请确认 paths.need_cleaned_dir 是非空 list"
            )
        # 保留兼容字段：data_root/result_dir 取第一个清理目录（业务方主 data 目录）
        self.data_root = self.need_cleaned_dirs[0].resolve()
        self.result_dir = str(self.need_cleaned_dirs[0])

        result_ext = pipeline.get("result_extraction", {})

        # 归档配置
        archive = pipeline.get("archive", {})
        self.archive_paths = archive.get("paths", ["data"])

        self.execution_mode = pipeline.get("execution_mode", "inline")
        self.variables = pipeline.get("variables", {})

    @classmethod
    def from_config_dict(cls, config: Dict[str, Any]) -> "WorkflowPipelineConfig":
        """从 config.json["pipeline"] 字段直接构造配置（YAML 路径已废弃）"""
        return cls(config)

    def get_step_script(self, step_name: str) -> Optional[Dict[str, Any]]:
        for step in self.steps:
            if step.get("name") == step_name:
                return step
        return None

    def should_run_step(self, step_name: str, round_num: int, build_cache_done: bool) -> bool:
        step = self.get_step_script(step_name)
        if step is None:
            return False
        if step.get("run_once", False) and build_cache_done:
            return False
        if step.get("round1_only", False) and round_num > 1:
            return False
        return True


class WorkflowPipelineExecutor(BaseEvaluator):
    def __init__(
        self,
        config: Dict[str, Any],
        round_num: int = 1,
        non_interactive: bool = False,
        workspace: str = "",
        args=None,
        eval_run: int = 1,
        eval_mode: str = "baseline",
        candidate_id: int = 1,
    ):
        super().__init__(config)
        self.pipeline_config = WorkflowPipelineConfig(config)
        self.round_num = round_num
        self.non_interactive = non_interactive
        self._workspace = Path(workspace).resolve() if workspace else Path.cwd().resolve()
        self._build_cache_done = False
        self._args = args
        self._eval_run = eval_run
        self._eval_mode = eval_mode
        self._candidate_id = candidate_id

    @property
    def evaluator_type(self) -> str:
        return "workflow_pipeline"

    def _get_case_ids_str(self) -> str:
        """从多源组装 case_ids 字符串（用于 ${CASE_IDS} 占位符替换）。

        优先级：pipeline variables > CLI 参数 > user-config.yaml。

        返回逗号分隔字符串是业务方命令协议要求（如 sdd-eval 的 `--req-id` 接受
        "RAN-1,RAN-2" 形式，见业务方命令定义）。框架内部全程以 list 形式持有，
        仅在这一步为业务方命令行做最终拼接，无法在框架层消除。
        """
        for key, value in self.pipeline_config.variables.items():
            if key in ("SKILLX_CASE_IDS", "CASE_IDS"):
                if isinstance(value, list):
                    val = ",".join(str(x).strip() for x in value if str(x).strip())
                else:
                    val = str(value).strip()
                if val:
                    return val
        if self._args:
            ids = getattr(self._args, "case_ids", None)
            if ids:
                if isinstance(ids, list):
                    return ",".join(str(x).strip() for x in ids if str(x).strip())
                return str(ids).strip()
        from orchestrators.workspace import get_case_ids
        yaml_ids = get_case_ids()
        if yaml_ids:
            return ",".join(yaml_ids)
        return ""

    def _resolve_activity(self) -> str:
        env_val = os.environ.get("SKILLX_ACTIVITY", "")
        if env_val:
            return env_val
        for key, value in self.pipeline_config.variables.items():
            if key in ("SKILLX_ACTIVITY", "ACTIVITY"):
                val = str(value).strip()
                if val:
                    return val
        activities = self.pipeline_config.activities or []
        if activities:
            return activities[0] if isinstance(activities, list) else str(activities)
        # 从步骤命令中提取 --nodes 值
        for step in self.pipeline_config.steps:
            cmd = step.get("command", "")
            m = re.search(r'--nodes\s+([^\s,]+)', cmd)
            if m:
                return m.group(1)
            m = re.search(r'--sub-activity\s+([^\s]+)', cmd)
            if m:
                return m.group(1)
        return ""

    def evaluate(self, skill_path: str) -> EvaluationResult:
        base_dir = self.pipeline_config.base_dir
        if not base_dir.exists():
            raise EvaluationError(f"业务方管道目录不存在: {base_dir}")
        return self._evaluate_inline(skill_path)

    # ── inline 原地评测方法 ────────────────

    def _evaluate_inline(self, skill_path: str) -> EvaluationResult:
        """
        inline 模式的原地评测流程。
        不创建沙箱，直接在业务方评测目录执行命令。
        完成后归档产物到 workspace，清理数据目录为下轮准备。
        """
        base_dir = self.pipeline_config.base_dir

        print(f"\n  [{'='*50}]")
        print(f"  [WorkflowPipeline] Round {self.round_num}: 原地评测（inline 模式）")
        print(f"  [{'='*50}]")
        print(f"  [WorkflowPipeline] 评测目录: {base_dir}")

        # 1. 清理配置指定的数据目录
        clean_eval_data_sandbox(base_dir, stage="pre_eval_inline", extra_clean_dirs=self.pipeline_config.need_cleaned_dirs)

        # 2. 构建环境并执行步骤
        env = self._build_inline_env()
        step_outputs = self._run_pipeline_steps_inline(env, base_dir)

        # 3. 归档到 workspace
        self._archive_inline_artifacts(base_dir, skill_path, step_outputs)

        # 4. 清理数据目录（为下轮准备）
        clean_eval_data_sandbox(base_dir, stage="post_eval_inline", extra_clean_dirs=self.pipeline_config.need_cleaned_dirs)

        # 5. 返回执行结果（分数由 ScoreAnalyzerAgent 独立提取）
        return self._build_result(step_outputs)

    def _build_inline_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        if not env.get("SKILLX_ACTIVITY"):
            env["SKILLX_ACTIVITY"] = self._resolve_activity()
        for key, value in self.pipeline_config.variables.items():
            env[key] = str(value).replace("${BASE_DIR}", str(self.pipeline_config.base_dir))
        # 评测流水线(phase1-build/phase2-exec/phase3-eval/phase4-diagnosis)用配置的评测模型
        # (`config/evolve-user-config.yaml` 的 `eval_model` 段,单点配置;模型变化只改 YAML 一处,不波及代码)。
        # 若不单独配置,评测 judge 会继承全局/优化模型(如教师模型 M3) → M3 Token 配额耗尽(429)
        # → 评测失败(phase3-eval 缺失/0 分) + 429 重试风暴(每轮 50-100 分钟)。这里仅覆盖评测子进程 env,不改 SDD评测Agent。
        _eval_model = _load_eval_model_config()
        if _eval_model.get("name"):
            env["ANTHROPIC_MODEL"] = _eval_model["name"]
        if _eval_model.get("base_url"):
            env["ANTHROPIC_BASE_URL"] = _eval_model["base_url"]
        # eval_model.api_key:评测走 ccr/本地 router 时,必须携带该 router 自己的 key。
        # 否则评测 cosight 继承全局 ANTHROPIC_AUTH_TOKEN(教师模型 key),被 router 以
        # 401 "Invalid API key" 拒绝(例如 ccr 127.0.0.1:3456 只认 ccr-secret-key)。
        if _eval_model.get("api_key"):
            env["ANTHROPIC_AUTH_TOKEN"] = _eval_model["api_key"]
        return env

    def _run_pipeline_steps_inline(
        self, env: Dict[str, str], base_dir: Path
    ) -> Dict[str, Dict[str, Any]]:
        step_outputs = {}
        print(f"  [WorkflowPipeline] 共 {len(self.pipeline_config.steps)} 个步骤: {[s.get('name', '?') for s in self.pipeline_config.steps]}")
        for step in self.pipeline_config.steps:
            step_name = step.get("name", "unknown")
            step_type = step.get("type", "script")
            if step_type == "cosight_command":
                step_result = self._run_cosight_command_step_inline(step, env, base_dir)
            elif step_type == "script":
                step_result = self._run_script_step_inline(step, env, base_dir)
            else:
                step_outputs[step_name] = {"status": "skipped", "reason": f"unsupported type={step_type}"}
                continue
            step_outputs[step_name] = step_result
        return step_outputs

    def _run_script_step_inline(
        self, step: Dict[str, Any], env: Dict[str, Any], base_dir: Path
    ) -> Dict[str, Any]:
        """使用 subprocess 真执行 script 类型步骤（与 cosight_command 的 LLM 模拟相对）。"""
        step_name = step.get("name", "unknown")
        command_template = step.get("command", "")
        if not command_template:
            return {"status": "error", "error": "未指定 command"}

        # 🆕 移除步骤级清理(2026-08-09):pre_script_step 在每个 script 步骤执行前清空 data/,
        # 会破坏同轮 phase1→2→3→4 的产物链(Phase 1 构建的 e2e-sets 在 Phase 2 步骤前被清 → Phase 2 找不到 input → 评测失败/0分)。
        # 清理只应在整轮评测前(pre_eval_inline)和整轮评测后(post_eval_inline)执行,同轮各 phase 共享产物。
        command = self._render_command(command_template, base_dir)

        command_dir = base_dir
        cd_match = re.match(r'^cd\s+(.+?)\s+&&\s+(.*)', command, re.DOTALL)
        if cd_match:
            command_dir = Path(cd_match.group(1))
            command = cd_match.group(2).strip()

        # 自动批准：检测到 `cosight -p` 时自动注入 --dangerously-skip-permissions
        # 解决：cosight -p 在默认权限模式下遇到敏感操作（Bash、写文件）会暂停等待用户批准，
        #       而 skillx-alpha-agents 是全自动 harness，没人交互。
        # 此注入默认开启；如需关闭，可在 step 配置中加 "auto_approve_cosight: false"。
        auto_approve_cosight = step.get("auto_approve_cosight", True)
        if auto_approve_cosight and self._is_cosight_p_command(command):
            command = self._inject_cosight_skip_permissions(command)
            print("    [auto-approve] 已为 cosight -p 注入 --dangerously-skip-permissions")

        # 修复 v2.8:对 `cosight -p` 包装的 slash command 命令默认 timeout=36000s(10 小时)
        # 根因:cosight -p 内部 ~600s 自动切后台会截断长任务(/sdd-eval 4 阶段完整跑需更久)
        # 业务方可用 step.timeout 显式覆盖（优先于本默认值）
        _is_cosight_p = self._is_cosight_p_command(command)
        _default_step_timeout = step.get("timeout", self.pipeline_config.timeout)
        if not _default_step_timeout and _is_cosight_p:
            _default_step_timeout = 36000  # 10 小时,根治 cosight -p 切后台截断
        step_timeout = _default_step_timeout or None
        print(f"\n  [WorkflowPipeline] 执行步骤 (script, inline): {step_name}")
        print(f"    command: {command[:200]}{'...' if len(command) > 200 else ''}")
        print(f"    cwd: {command_dir}")
        if step_timeout:
            print(f"    timeout: {step_timeout}s")

        # 日志路径：落到 workspace 对应 run 目录下（与 score.json/data 归档同层级）
        # baseline 模式 → baseline/run_{eval_run}/logs/；轮次模式 → round_{N}/candidate_{K}/run_{M}/logs/
        if self._eval_mode == "baseline":
            log_dir = self._workspace / "baseline" / f"run_{self._eval_run}" / "logs"
        else:
            log_dir = self._workspace / f"round_{self.round_num}" / f"candidate_{self._candidate_id}" / f"run_{self._eval_run}" / "logs"
        log_path = log_dir / f"eval_{step_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

        try:
            # detached Popen + 安静轮询（不再阻塞主流程；stdout/stderr 重定向到 log_path）
            result = _run_step_with_poll(
                cmd=command,
                cwd=command_dir,
                env=env,
                log_path=log_path,
                step_timeout=step_timeout,
                step_name=step_name,
            )
            log_path = Path(result["log_path"])
            returncode = result["returncode"]

            if result["timed_out"]:
                print(f"\n  [WorkflowPipeline] ❌ 步骤 '{step_name}' 超时（{step_timeout}s）")
                print(f"    日志: {log_path}")
                return {
                    "status": "error",
                    "error": f"timeout after {step_timeout}s",
                    "log_path": str(log_path),
                }

            # 修复 v2.8:检测 cosight -p 内部超时把任务切到后台的事实
            # 根因:cosight -p 在内部 ~600s 后会自动切后台并立即返回(原 returncode=0),
            #       表面看是"成功"实际任务未完成,不能当 ok 处理
            # 触发时:返回 error 状态,带 cosight_bg_switched=True 标志
            # (stdout 现已写入 log_path,从文件读取用于检测)
            if returncode == 0 and _is_cosight_p:
                full_stdout = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
                if self._detect_cosight_background_switch(full_stdout):
                    with log_path.open("a", encoding="utf-8") as log_f:
                        log_f.write("\n[ERROR] cosight -p 自动切到后台,任务未完成(根因:cosight 内部超时)\n")
                    print("    [bg-switch] ❌ 检测到 cosight -p 自动切到后台,任务未完成")
                    print("    [bg-switch] 💡 解决:已自动加 10 小时 timeout;如仍复现,需查 cosight 端配置")
                    return {
                        "status": "error",
                        "error": "cosight_bg_switched: cosight -p 内部超时切到后台,任务未完成",
                        "returncode": -1,
                        "log_path": str(log_path),
                        "cosight_bg_switched": True,
                    }

            if returncode == 0:
                return {"status": "ok", "returncode": 0, "log_path": str(log_path)}
            # 命令执行失败时，给出明确诊断信息（避免用户对 cwd 和命令解析产生混淆）
            self._print_script_failure_hint(step_name, command, command_dir, returncode, log_path)
            return {
                "status": "error",
                "error": f"non-zero exit: {returncode}",
                "returncode": returncode,
                "log_path": str(log_path),
            }
        except Exception as e:
            self._print_script_failure_hint(step_name, command, command_dir, -1, log_path, exc=e)
            return {"status": "error", "error": str(e)}

    def _print_script_failure_hint(
        self,
        step_name: str,
        command: str,
        command_dir: Path,
        returncode: int,
        log_path: Path,
        exc: Optional[Exception] = None,
    ) -> None:
        """脚本执行失败时打印可操作的诊断提示（cwd、命令、常见错误原因）。"""
        print(f"\n  [WorkflowPipeline] ❌ 步骤 '{step_name}' 执行失败")
        print(f"    命令: {command[:200]}{'...' if len(command) > 200 else ''}")
        print(f"    cwd : {command_dir}")
        print(f"    返回码: {returncode}")
        print(f"    日志: {log_path}")
        if exc is not None:
            print(f"    异常: {exc}")

        # 常见错误模式提示
        cmd_first_token = (command or "").lstrip().split(maxsplit=1)[0] if command else ""
        hints: List[str] = []
        if cmd_first_token.startswith("/"):
            hints.append(
                "  ⚠️  命令以 '/' 开头 —— 这看起来像 cosight 的 slash command。\n"
                "     编排器通过 subprocess.Popen shell=True 执行命令（cwd=base_dir），slash command 在 shell 中无法识别。\n"
                "     正确做法：直接调用底层 Python 脚本，例如：\n"
                "       python3 <your_eval_script>.py --arg value\n"
                "     或者把 slash command 包到 cosight -p 里：\n"
                "       cosight -p \"/<your-slash-cmd> --arg value\"\n"
                "     或者改用 type=cosight_command 的 YAML 配置。"
            )
        # 127 = command not found；典型场景：脚本不在 PATH / cwd 错了
        if returncode == 127 or (exc is not None and isinstance(exc, FileNotFoundError)):
            hints.append(
                "  ⚠️  返回码 127 / FileNotFoundError 通常意味着：\n"
                "     1) 脚本不在 PATH 中（推荐用相对路径 + python3 前缀，cwd=base_dir 时用 scripts/xxx.py）；\n"
                "     2) cwd 与你预期的不一致（实际执行目录已在上方打印）；\n"
                "     3) 命令本身拼写错误。"
            )
        if not hints:
            hints.append(
                "  💡 请检查：命令是否依赖 PATH 变量？是否需要绝对路径？\n"
                "     cwd 已在上方打印，相对路径相对的是该 cwd，不是项目根。"
            )
        for h in hints:
            print(h)

    def _render_command(self, command_template: str, base_dir: Path) -> str:
        """渲染命令模板中的变量（${CASE_IDS}/${ACTIVITY}/${SKILL_PATH}/${BASE_DIR}）。"""
        activity = (
            self.pipeline_config.variables.get("ACTIVITY")
            or self.pipeline_config.variables.get("SKILLX_ACTIVITY")
            or os.environ.get("SKILLX_ACTIVITY", "")
        )
        command = command_template.replace("${CASE_IDS}", self._get_case_ids_str())
        command = command.replace("${ACTIVITY}", str(activity))
        skill_path_str = ""
        if self._args and getattr(self._args, 'skill_path', None):
            skill_path_str = str(self._args.skill_path)
        command = command.replace("${SKILL_PATH}", skill_path_str)
        command = command.replace("${SANDBOX_DIR}", str(base_dir))
        command = command.replace("${BASE_DIR}", str(base_dir))
        # 注入每轮/候选上下文（供 mock 评测区分基线/候选/不同轮次）
        command = command.replace("${ROUND_NUM}", str(self.round_num))
        command = command.replace("${CANDIDATE_ID}", str(self._candidate_id))
        command = command.replace("${EVAL_RUN}", str(self._eval_run))
        for key, value in self.pipeline_config.variables.items():
            command = command.replace(f"${{{key}}}", str(value))
        return command

    def _check_eval_artifacts(self, base_dir: Path, last_count: int = 0) -> int:
        """检查评测产物，返回当前结果文件数量。

        用于辅助判断 cosight -p 是否完成：当评测产物目录出现新的
        结果文件时，说明评测任务已经完成。
        """
        # 扫描 data/ 下所有 JSON 产物（不硬编码 phase 目录名）
        data_dir = base_dir / "data"
        if not data_dir.exists():
            return 0
        count = len(list(data_dir.rglob("*.json")))
        return count

    @staticmethod
    def _is_cosight_p_command(command: str) -> bool:
        """检测命令是否调用了 `cosight -p`（或 `cosight --print`）。

        匹配模式（按 token 切分后的第一个可执行文件名）：
        - `cosight -p "..."`
        - `cosight --print ...`
        - `/usr/bin/cosight -p ...`
        - 包含路径前缀的 `cosight` 可执行文件

        排除条件：
        - 已经包含 `--dangerously-skip-permissions` / `--allow-dangerously-skip-permissions`
        - 粘连形式（`cosight -p"x"` 不匹配，因为 `_inject_cosight_skip_permissions`
          需要 -p 后有空格才能正确插入参数；如需支持，请用 `cosight -p "x"`）
        """
        if not command:
            return False
        cmd = command.strip()
        # 已经手动注入过，不再重复
        if "--dangerously-skip-permissions" in cmd or "--allow-dangerously-skip-permissions" in cmd:
            return False
        # 切分第一个 token（支持引号）
        try:
            tokens = shlex.split(cmd, posix=True)
        except ValueError:
            tokens = cmd.split()
        if not tokens:
            return False
        first = tokens[0].rsplit("/", 1)[-1]  # 去掉路径前缀
        if first not in ("cosight", "claude"):
            return False
        # 必须包含 -p 或 --print（标准形式）
        return any(t in ("-p", "--print") for t in tokens[1:5])

    @staticmethod
    def _inject_cosight_skip_permissions(command: str) -> str:
        """在 `cosight -p` 命令中自动注入 `--dangerously-skip-permissions` 参数。

        注入位置：在 `cosight -p "<prompt>"` 字符串之后追加 `--dangerously-skip-permissions`。
        这样 cosight 进程会绕过所有权限检查（适用于 orchestrator 的全自动场景）。

        注意：
        - 不会破坏引号内含空格的内容（用 shlex.split 解析第一个 prompt 边界）
        - 如果命令已经包含 --dangerously-skip-permissions，则不重复注入
        """
        cmd = command.strip()
        if "--dangerously-skip-permissions" in cmd or "--allow-dangerously-skip-permissions" in cmd:
            return command
        # 找到第一个 `-p` 或 `--print`，在其后插入参数（确保前后有空格）
        m = re.search(r'(?:^|\s)(--print|-p)(?:\s|$)', cmd)
        if not m:
            return command
        # m.start() 指向 -p 前面的空白，m.end() 指向 -p 后面的空白之后
        # 我们要在 -p 标志后、prompt 字符串前插入 --dangerously-skip-permissions
        flag_end = m.end() - 1  # -p/--print 标志的结束位置（最后一个字符）
        # 确保 -p 标志和后续内容之间有空格
        if flag_end + 1 < len(cmd) and cmd[flag_end + 1] == " ":
            # 已有空格，在 -p 标志后立即插入新参数
            injected = (
                cmd[: flag_end + 1]
                + "--dangerously-skip-permissions "
                + cmd[flag_end + 1 :]
            )
        else:
            # -p 后面没有空格（如 `cosight -p"test"` 罕见情况），强制补空格
            injected = (
                cmd[: flag_end + 1]
                + " --dangerously-skip-permissions "
                + cmd[flag_end + 1 :]
            )
        return injected

    @staticmethod
    def _detect_cosight_background_switch(stdout: str) -> bool:
        """
        检测 cosight -p 是否因为内部超时把任务切到后台（v2.8 修复）。

        根因：cosight -p 在内部 ~600s 超时后会把任务切到后台并立即返回（原 returncode=0），
        表面看是「成功」实际任务未完成，不能当 ok 处理。

        检测策略：从 cosight 实际切后台时的 stdout 模板提取中英文关键词。
        任何关键词命中即返回 True，调用方应把该次执行标记为 N/A（不归档 / 标根因）。

        Args:
            stdout: subprocess.Popen 的完整 stdout 输出

        Returns:
            True 表示检测到切到后台的事实；False 表示正常完成或非 cosight -p 输出
        """
        if not stdout:
            return False
        # 从实测日志提取的关键词（涵盖中英文常见变体 + 繁体）
        bg_indicators = [
            "切到后台",            # "已切到后台执行"
            "切至后台",            # 变体
            "切換到後台",          # 繁体
            "已切换到后台",        # 变体
            "已切换至后台",        # 变体
            "后台执行中",          # "Phase 2 正在后台执行中"
            "已移到后台",          # 变体
            "已自动切换到后台",    # "600秒超时后已自动切换到后台执行"
            "background agent",    # 英文: "started as a background agent"
            "moved to background", # 英文
            "task was backgrounded",  # 英文
        ]
        return any(ind.lower() in stdout.lower() for ind in bg_indicators)

    def _run_cosight_command_step_inline(
        self, step: Dict[str, Any], env: Dict[str, Any], base_dir: Path
    ) -> Dict[str, Any]:
        step_name = step.get("name", "unknown")
        command_template = step.get("command", "")
        if not command_template:
            return {"status": "error", "error": "未指定 command"}

        activity = (
            self.pipeline_config.variables.get("ACTIVITY")
            or self.pipeline_config.variables.get("SKILLX_ACTIVITY")
            or os.environ.get("SKILLX_ACTIVITY", "")
        )
        command = command_template.replace("${CASE_IDS}", self._get_case_ids_str())
        command = command.replace("${ACTIVITY}", str(activity))
        # ${SKILL_PATH} 使用当前评测的 skill 路径（args.skill_path），
        # 而非原始路径（args.skill_paths），确保优化后的 skill 被正确传递
        skill_path_str = ""
        if self._args and getattr(self._args, 'skill_path', None):
            skill_path_str = str(self._args.skill_path)
        command = command.replace("${SKILL_PATH}", skill_path_str)
        command = command.replace("${SANDBOX_DIR}", str(base_dir))
        command = command.replace("${BASE_DIR}", str(base_dir))
        for key, value in self.pipeline_config.variables.items():
            command = command.replace(f"${{{key}}}", str(value))

        # 提取 cd 前缀目录作为 cwd（支持 "cd xxx && ..." 格式）
        command_dir = base_dir
        cd_match = re.match(r'^cd\s+(.+?)\s+&&\s+(.*)', command, re.DOTALL)
        if cd_match:
            command_dir = Path(cd_match.group(1))
            command = cd_match.group(2).strip()

        cmd = ["claude", "-p", command.strip(), "--dangerously-skip-permissions"]

        step_timeout = step.get("timeout", self.pipeline_config.timeout)
        print(f"\n  [WorkflowPipeline] 执行步骤 (cosight_command, inline): {step_name}")
        print(f"    command: {command[:200]}{'...' if len(command) > 200 else ''}")

        # 🆕 移除步骤级清理(2026-08-09):pre_cosight_command_step 在每个 cosight_command 步骤执行前清空 data/,
        # 破坏同轮 phase1→2→3→4 产物链(Phase 1 的 e2e-sets 在 Phase 2 前被清)。清理只在整轮评测前/后执行。

        # 日志路径：落到 workspace 对应 run 目录下（与 score.json/data 归档同层级）
        # baseline 模式 → baseline/run_{eval_run}/logs/；轮次模式 → round_{N}/candidate_{K}/run_{M}/logs/
        if self._eval_mode == "baseline":
            log_dir = self._workspace / "baseline" / f"run_{self._eval_run}" / "logs"
        else:
            log_dir = self._workspace / f"round_{self.round_num}" / f"candidate_{self._candidate_id}" / f"run_{self._eval_run}" / "logs"
        log_path = log_dir / f"eval_{step_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

        try:
            # detached Popen + 安静轮询（cosight -p 长任务不阻塞主流程；
            # stdout/stderr 重定向到 log_path，不再实时流式 —— "安静轮询" 设计）
            result = _run_step_with_poll(
                cmd=cmd,
                cwd=command_dir,
                env=env,
                log_path=log_path,
                step_timeout=step_timeout,
                step_name=step_name,
            )
            log_path = Path(result["log_path"])
            stdout_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            stdout_tail = stdout_text[-500:] if stdout_text else ""

            if result["timed_out"]:
                return {"status": "error", "returncode": -1, "stdout_tail": stdout_tail,
                        "error": f"timeout after {step_timeout}s"}
            if result["returncode"] != 0:
                return {"status": "error", "returncode": result["returncode"], "stdout_tail": stdout_tail}
            return {"status": "ok", "returncode": 0, "stdout_tail": stdout_tail}

        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _archive_inline_artifacts(
        self, base_dir: Path, skill_path: Optional[str], step_outputs: Dict
    ) -> None:
        archive_dir = self._get_archive_dir()
        archive_dir.mkdir(parents=True, exist_ok=True)

        _base_dir = archive_dir.parent
        skill_dest_dir = _base_dir / "skill"
        # run 子目录（run_1/run_2/...）不创建 skill 副本/快捷方式；
        # 父级（baseline 或 round_N）的 skill 副本已经存在，按需直接引用即可。
        if not skill_dest_dir.exists() and not _base_dir.name.startswith("run_"):
            skill_ws_dir = self._workspace / "skill"
            if skill_ws_dir.exists():
                # 首次拷贝（baseline/skill 或 round_N/skill）：实际拷贝
                skill_dest_dir.mkdir(parents=True, exist_ok=True)
                for item in skill_ws_dir.iterdir():
                    dest_item = skill_dest_dir / item.name
                    if item.is_dir():
                        if dest_item.exists():
                            shutil.rmtree(str(dest_item))
                        shutil.copytree(str(item), str(dest_item))
                    else:
                        shutil.copy2(str(item), str(dest_item))

        for rel_path in self.pipeline_config.archive_paths:
            src = base_dir / rel_path
            if src.exists():
                if rel_path == "data" and archive_dir.name == "data":
                    # 修复 Baseline 覆盖：同一 dest 已有归档且与本次 src 不同 → 改写到 _v2 子目录，保留旧 baseline 不变。
                    dest = self._resolve_baseline_archive_dest(src, archive_dir)
                    for item in src.iterdir():
                        dest_item = dest / item.name
                        if dest_item.exists():
                            if dest_item.is_dir():
                                shutil.rmtree(str(dest_item))
                            else:
                                dest_item.unlink()
                        if item.is_dir():
                            shutil.copytree(str(item), str(dest_item))
                        else:
                            shutil.copy2(str(item), str(dest_item))
                    self._write_archive_marker(dest, src)
                    print(f"  [WorkflowPipeline] 已归档 data/ 到 {dest}")
                else:
                    dest = archive_dir / rel_path
                    if dest.exists():
                        shutil.rmtree(str(dest))
                    shutil.copytree(str(src), str(dest))
                    print(f"  [WorkflowPipeline] 已归档 {rel_path}/ 到 {dest}")

        print(f"  [WorkflowPipeline] 已归档 inline 产物: {archive_dir}")

    def _build_result(
        self,
        step_outputs: Dict[str, Dict[str, Any]],
    ) -> EvaluationResult:
        """构建 EvaluationResult（分数由 ScoreAnalyzerAgent 独立提取）。"""
        # 判断步骤执行状态
        all_ok = all(v.get("status") == "ok" for v in step_outputs.values() if v.get("status") != "skipped")
        status = "ok" if all_ok else "partial"

        # 统计各步骤状态
        step_status = {k: v.get("status") for k, v in step_outputs.items()}

        # 修复 v2.8:检测 cosight -p 切后台截断 → 标记 N/A(不计分,避免误判为 0 误导后续迭代)
        # 根因:cosight -p 内部 ~600s 自动切后台后立即返回,后续阶段可能没跑
        # 行为:score=None(不是 0,不被平均分计算包含) + rating="N/A" + 在 metadata 显式标识
        bg_switched = any(
            v.get("cosight_bg_switched", False) for v in step_outputs.values()
        )
        if bg_switched:
            print("  [N/A] cosight -p 自动切到后台,本轮结果标记为 N/A(不计分)")
            return EvaluationResult(
                score=None,  # N/A:不参与聚合,避免误导后续迭代
                rating="N/A",
                gaps=[{
                    "severity": "critical",
                    "type": "cosight_bg_switched",
                    "message": "cosight -p 内部超时切到后台,任务未完成,本轮不计分",
                    "root_cause": "cosight_internal_timeout",
                    "fix_suggestion": "重跑本轮 / 调长 cosight 端 timeout / 改用 nohup+轮询模式",
                }],
                improvements=["重跑本轮 baseline / 检查 cosight 端 timeout 配置"],
                evaluator_type="workflow_pipeline",
                metadata={
                    "round": self.round_num,
                    "pipeline_steps": step_status,
                    "activities": self.pipeline_config.activities,
                    "archive_path": str(self._workspace / f"round_{self.round_num}"),
                    "execution_status": "N/A",
                    "na_reason": "cosight_bg_switched",
                },
            )

        return EvaluationResult(
            score=0.0,  # 分数由 ScoreAnalyzerAgent 提取
            rating="PENDING",
            gaps=[],  # gap 由 ScoreAnalyzerAgent 分析
            improvements=[],
            evaluator_type="workflow_pipeline",
            metadata={
                "round": self.round_num,
                "pipeline_steps": step_status,
                "activities": self.pipeline_config.activities,
                "archive_path": str(self._workspace / f"round_{self.round_num}"),
                "execution_status": status,
            },
        )

    def _src_signature(self, src: Path) -> str:
        """对 src/data 计算稳定 hash，用于判断源是否变化（immutable baseline 判重）。"""
        h = hashlib.sha256()
        for p in sorted(src.rglob("*")):
            if p.is_file():
                h.update(p.relative_to(src).as_posix().encode())
                h.update(b"\0")
                h.update(p.read_bytes())
                h.update(b"\0")
        return h.hexdigest()[:16]

    def _read_archive_marker(self, dest: Path) -> Dict[str, Any] | None:
        marker = dest / "archived_marker.json"
        if marker.exists():
            try:
                return json.loads(marker.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def _write_archive_marker(self, dest: Path, src: Path) -> None:
        """在 dest 下写归档 marker，记录 src hash + 时间戳，用于下次的 immutable 判重。"""
        try:
            (dest / "archived_marker.json").write_text(
                json.dumps({
                    "source_hash": self._src_signature(src),
                    "archived_at": datetime.now().isoformat(timespec="seconds"),
                }, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:  # marker 是 best-effort，不阻塞主流程
            print(f"  [Archive] 写 archived_marker.json 失败 (best-effort): {e}")

    def _resolve_baseline_archive_dest(self, src: Path, primary_dest: Path) -> Path:
        """不可变 baseline 解析：primary 已存在历史归档且 src 与上次不同 → 返回 *_vN/data。

        仅在 baseline 模式 (_eval_mode == 'baseline') 启用一次保护，避免 baseline/run_1/data 被静默刷新。
        """
        marker = self._read_archive_marker(primary_dest)
        if not marker or not marker.get("source_hash"):
            return primary_dest  # 首次归档或旧数据无 marker，正常写 primary
        if marker["source_hash"] == self._src_signature(src):
            return primary_dest  # 内容未变，仍走 primary
        # 已发生覆盖风险 → 改写 _v2 子目录
        suffix = 2
        run_dir = primary_dest.parent
        while True:
            candidate = run_dir.parent / f"{run_dir.name}_v{suffix}" / "data"
            if not candidate.exists():
                candidate.parent.mkdir(parents=True, exist_ok=True)
                print(f"  [BaselineArchive] 旧 baseline 不被覆盖，转写入 {candidate}")
                return candidate
            suffix += 1

    def _get_archive_dir(self) -> Path:
        """获取归档目录。

        优先级:
        1. _eval_mode == "baseline" → baseline/run_{eval_run}/
        2. _candidate_id > 0 → round_{round_num}/candidate_{candidate_id}/run_{eval_run}/
        3. 兜底: round_{round_num}/ (深度模式)

        注:baseline 阶段即使 round_num == 0,也强制走 baseline/run_{eval_run}/,
        避免基线产物被误归到 round_0/data/ (历史 bug)。
        """
        if self._eval_mode == "baseline":
            run_dir = self._workspace / "baseline" / f"run_{self._eval_run}"
        elif self._candidate_id > 0:
            run_dir = self._workspace / f"round_{self.round_num}" / f"candidate_{self._candidate_id}" / f"run_{self._eval_run}"
        else:
            run_dir = self._workspace / f"round_{self.round_num}"
        run_dir.mkdir(parents=True, exist_ok=True)
        data_dir = run_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        # 诊断日志:确认归档路径选择正确
        print(f"  [Archive] eval_mode={self._eval_mode} round_num={self.round_num} "
              f"candidate_id={self._candidate_id} eval_run={self._eval_run} → {data_dir}", flush=True)
        return data_dir


def create_pipeline_executor(
    pipeline_config_dict: Optional[Dict[str, Any]] = None,
    pipeline_eval_cmd: str = "",
    round_num: int = 1,
    non_interactive: bool = False,
    score_agg: str = "mean",
    workspace: str = "",
    args=None,
    eval_run: int = 1,
    eval_mode: str = "baseline",
    candidate_id: int = 1,
) -> WorkflowPipelineExecutor:
    """创建 Pipeline Executor

    参数：
        pipeline_config_dict: 来自 config.json["pipeline"] 字段的 dict
            （由 orchestrator 的 populate_pipeline_in_config 写入并下发到 args）。
            必填——若未提供，应在外层 fail-fast 报错。
        pipeline_eval_cmd: 业务方传入的评测命令字符串，用于在没有显式 step
            时注入一个 cosight_command 步骤（兼容 eval 模式兜底）。
    """
    if not pipeline_config_dict:
        raise ValueError(
            "缺少 pipeline 配置：请在 config.json[\"pipeline\"] 注入或调用 "
            "populate_pipeline_in_config(args) 补全"
        )

    config_dict = {"pipeline": dict(pipeline_config_dict)}

    # 兜底：如果 config 中 steps 为空但有 pipeline_eval_cmd，注入 cosight_command 步骤
    if not config_dict["pipeline"].get("steps") and pipeline_eval_cmd:
        config_dict["pipeline"]["steps"] = [{
            "name": "eval",
            "type": "cosight_command",
            "command": pipeline_eval_cmd,
            "timeout": 0,
        }]

    # 注入 pipeline_eval_cmd 到 variables（向下兼容）
    if pipeline_eval_cmd:
        config_dict["pipeline"].setdefault("variables", {})["PIPELINE_EVAL_CMD"] = pipeline_eval_cmd

    return WorkflowPipelineExecutor(
        config=config_dict,
        round_num=round_num,
        non_interactive=non_interactive,
        workspace=workspace,
        args=args,
        eval_run=eval_run,
        eval_mode=eval_mode,
        candidate_id=candidate_id,
    )
