"""子 Agent 运行时无关执行器（runtime-agnostic agent runner）。

在源插件 `tools._call_claude_pipe`（硬编码 `claude -p`）之上抽象一层 provider，
让同一份 orchestrator 代码能驱动三种 headless agent CLI：

- claude  : `claude -p <prompt> --append-system-prompt <system> --allowedTools ... --dangerously-skip-permissions`
- cosight : 同 claude（`cosight -p` 参数面同构），额外注入项目级 `.cosight/settings.json` env
- codex   : 临时 AGENTS.md 注入 system + `codex exec -C <workdir> --allow-tools ... --sandbox ...`
- dsh     : `dsh --profile headless "<combined system+prompt>"`

选择优先级：显式传入 > env `SKILLX_AGENT_CLI` > 默认 `claude`（向后兼容，行为与旧的
`_call_claude_pipe` 完全一致）。

能力降级矩阵：
| 能力 | claude | cosight | codex | dsh |
|---|---|---|---|---|
| system 注入 | --append-system-prompt | --append-system-prompt | 临时 AGENTS.md | prompt 内联合并 |
| 工具审计 raw_jsonl(stream-json) | ✅ | ✅ | ❌ None | ❌ None |
| 权限跳过 | --dangerously-skip-permissions | --dangerously-skip-permissions | --sandbox danger-full-access | 无(降级) |
| 项目模型/路由 env | 继承父会话 | 读项目 .cosight/settings.json | 继承父会话 | 继承父会话 |
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

RUNNER_NAMES: Tuple[str, ...] = ("claude", "cosight", "codex", "dsh")

# codex 的 Bash 工具无 claude 的 `Bash(mkdir,cp,...)` 子过滤语法,单独给一套简化白名单。
_CODEX_ALLOWED_TOOLS_DEFAULT = "Read,Edit,Write,Glob,Grep,Bash"


@dataclass
class RunResult:
    """一次子 Agent 调用的完整结果。

    raw_jsonl 仅 claude 的 stream-json 模式产生;codex/dsh 下为 None，
    消费方（tools._summarize_tool_use_from_jsonl）已对 None 容错跳过。
    """

    stdout: str
    stderr: str
    returncode: Optional[int]
    duration_sec: float
    exception_str: Optional[str]
    raw_jsonl: Optional[str]


def _quote(s: str) -> str:
    return f'"{s}"' if s and (" " in s or "\n" in s) else s


class RunError(Exception):
    """子 Agent 进程启动或执行失败（不用于业务失败，仅进程层异常）。"""


def _load_project_settings_env() -> dict:
    """读项目 `.cosight/settings.json` + `settings.local.json` 的 env（项目级模型/路由配置）。

    Cosight 运行时使用：project 根的 `.cosight/settings.json` 生效 → `cosight -p` 子进程继承。
    同时绕过 cosight 默认 router（isRouterEnabled 默认 true）导致的"项目模型被转发"问题：
    项目 settings.env 的 `COSIGHT_ROUTER_ENABLED=false` 覆盖后 cosight 走 firstParty 直连 M3。
    claude/codex/dsh 不经过此函数（它们各自继承父会话环境）。
    """
    merged: dict = {}
    try:
        _cwd = Path(os.getcwd())
        for root in [_cwd, *_cwd.parents]:
            settings_file = root / ".cosight" / "settings.json"
            local_file = root / ".cosight" / "settings.local.json"
            if settings_file.exists() or local_file.exists():
                for f in (settings_file, local_file):
                    if not f.exists():
                        continue
                    try:
                        _data = json.loads(f.read_text(encoding="utf-8"))
                        for _k, _v in (_data.get("env") or {}).items():
                            if isinstance(_v, str):
                                merged[_k] = _v
                    except Exception:
                        pass
                break  # 找到项目 settings 即停（向上不再找）
    except Exception:
        pass
    return merged


def _run_subprocess(
    cmd: list,
    *,
    timeout: Optional[int],
    cwd: Optional[str],
    env: Optional[dict] = None,
) -> RunResult:
    """通用 subprocess 执行骨架，永不抛异常（进程异常计入 exception_str）。"""
    run_kwargs: dict = dict(
        capture_output=True,
        text=True,
        env=env if env is not None else dict(os.environ),
    )
    if timeout is not None:
        run_kwargs["timeout"] = timeout
    if cwd is not None:
        run_kwargs["cwd"] = cwd

    started = time.monotonic()
    stdout = ""
    stderr = ""
    returncode: Optional[int] = None
    exception_str: Optional[str] = None
    try:
        result = subprocess.run(cmd, **run_kwargs)
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        returncode = result.returncode
    except subprocess.TimeoutExpired as e:
        exception_str = f"TimeoutExpired (timeout={timeout}s)"
        raw_out = e.stdout or b""
        raw_err = e.stderr or b""
        stdout = raw_out.decode("utf-8", errors="replace") if isinstance(raw_out, bytes) else (raw_out or "")
        stderr = raw_err.decode("utf-8", errors="replace") if isinstance(raw_err, bytes) else (raw_err or "")
    except Exception as e:  # noqa: BLE001 - 统一收敛为 exception_str
        exception_str = f"{type(e).__name__}: {e}"

    duration_sec = time.monotonic() - started
    return RunResult(
        stdout=stdout.strip(),
        stderr=stderr.strip(),
        returncode=returncode,
        duration_sec=duration_sec,
        exception_str=exception_str,
        raw_jsonl=None,
    )


class ClaudeRunner:
    """Claude Code headless：`claude -p` + `--append-system-prompt`。

    命令构造由 `binary` / `extra_env()` 参数化 —— CosightRunner 继承复用，
    仅换 binary 与注入项目级 env。
    """

    name = "claude"
    binary = "claude"

    def extra_env(self) -> Optional[dict]:
        """子进程额外 env（默认无；Cosight 注入项目模型配置）。"""
        return None

    def run(
        self,
        system: str,
        prompt: str,
        *,
        timeout: Optional[int] = None,
        settings_path: Optional[str] = None,
        output_format: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> RunResult:
        cmd = [self.binary, "-p", prompt, "--append-system-prompt", system]
        if not os.environ.get("SKILLX_AGENT_ALLOWED_TOOLS_OFF"):
            allowed = os.environ.get(
                "SKILLX_AGENT_ALLOWED_TOOLS",
                "Read,Write,Edit,Bash(mkdir,cp,ls,find,grep),Glob,Grep",
            )
            cmd.extend(["--allowedTools", allowed])
        if not os.environ.get("SKILLX_AGENT_SKIP_PERMISSIONS_OFF"):
            cmd.append("--dangerously-skip-permissions")
        if settings_path:
            cmd.extend(["--settings", settings_path])
        if output_format:
            cmd.extend(["--output-format", output_format])
            cmd.append("--verbose")

        env: Optional[dict] = None
        extra = self.extra_env()
        if extra:
            env = dict(os.environ)
            env.update(extra)
        res = _run_subprocess(cmd, timeout=timeout, cwd=cwd, env=env)
        if res.returncode not in (0, None):
            print(f"  ⚠️ {self.binary} -p 返回码 {res.returncode}，stderr={res.stderr[-300:]!r}")
        if not res.stdout:
            print(f"  ⚠️ {self.binary} -p stdout 为空 (returncode={res.returncode}, stderr={res.stderr[:200]!r})")
        else:
            print(
                f"  [{self.binary} -p] returncode={res.returncode} stdout={len(res.stdout)}B "
                f"stderr={len(res.stderr)}B output_format={output_format or 'text'}"
            )
            print(f"  [{self.binary} -p stdout tail] {res.stdout[-200:]!r}")

        # stream-json 模式:从 stdout jsonl 里抽最末 result 帧作为最终文本
        final_text = res.stdout
        raw_jsonl: Optional[str] = None
        if output_format == "stream-json" and res.stdout:
            try:
                lines = [l for l in res.stdout.split("\n") if l.strip()]
                last_result_text: Optional[str] = None
                for line in lines:
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") == "result" and isinstance(obj.get("result"), str):
                        last_result_text = obj["result"]
                if last_result_text is not None:
                    final_text = last_result_text
                raw_jsonl = res.stdout
            except Exception as e:  # noqa: BLE001
                print(
                    f"  [stream-json parse fail] {type(e).__name__}: {e}",
                    file=__import__("sys").stderr,
                )
                raw_jsonl = None
                final_text = res.stdout

        return RunResult(
            stdout=final_text.strip(),
            stderr=res.stderr,
            returncode=res.returncode,
            duration_sec=res.duration_sec,
            exception_str=res.exception_str,
            raw_jsonl=raw_jsonl,
        )


class CosightRunner(ClaudeRunner):
    """Cosight headless：`cosight -p`，命令面与 claude 同构，继承 ClaudeRunner。

    唯一差异：binary 换 `cosight`，且每次调用注入项目级 `.cosight/settings.json`
    env（经 `_load_project_settings_env`）+ `COSIGHT_LOG_LEVEL=warn`，使子进程用项目
    模型并绕 router 直连 M3。stream-json 工具审计流与 claude 一致，raw_jsonl 支持。
    """

    name = "cosight"
    binary = "cosight"

    def extra_env(self) -> Optional[dict]:
        return {**_load_project_settings_env(), "COSIGHT_LOG_LEVEL": "warn"}


class CodexRunner:
    """Codex headless：临时 AGENTS.md 注入 system + `codex exec -C <dir>`。

    codex 无 claude 的 stream-json 工具审计流 → raw_jsonl 恒为 None（降级）。
    """

    name = "codex"

    _supports_allow_tools = None  # 懒探测：不同 codex 版本参数面不同

    @classmethod
    def _allow_tools_supported(cls) -> bool:
        """探测 `codex exec --allow-tools` 是否受支持（0.16x+ 已移除）。"""
        if cls._supports_allow_tools is None:
            try:
                out = subprocess.run(
                    ["codex", "exec", "--help"],
                    capture_output=True, text=True, timeout=10,
                ).stdout
                cls._supports_allow_tools = "--allow-tools" in out
            except Exception:
                cls._supports_allow_tools = False
        return bool(cls._supports_allow_tools)

    def run(
        self,
        system: str,
        prompt: str,
        *,
        timeout: Optional[int] = None,
        settings_path: Optional[str] = None,
        output_format: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> RunResult:
        # system 提示写入一个干净 temp 工作目录的 AGENTS.md，codex 在 -C 下自动加载
        with tempfile.TemporaryDirectory(prefix="skillx-codex-") as tmp:
            (Path(tmp) / "AGENTS.md").write_text(system or "", encoding="utf-8")

            cmd = ["codex", "exec", "-C", tmp, "--skip-git-repo-check"]
            if not os.environ.get("SKILLX_AGENT_ALLOWED_TOOLS_OFF") and self._allow_tools_supported():
                allowed = os.environ.get("SKILLX_AGENT_CODEX_TOOLS", _CODEX_ALLOWED_TOOLS_DEFAULT)
                cmd.extend(["--allow-tools", allowed])
            if not os.environ.get("SKILLX_AGENT_SKIP_PERMISSIONS_OFF"):
                sandbox = os.environ.get("SKILLX_AGENT_SANDBOX", "danger-full-access")
                cmd.extend(["--sandbox", sandbox])
            # codex exec 把提示作为位置参数;多行时直接传,交给子进程 argv
            cmd.append(prompt)

            res = _run_subprocess(cmd, timeout=timeout, cwd=cwd)
            if res.returncode not in (0, None):
                print(f"  ⚠️ codex exec 返回码 {res.returncode}，stderr={res.stderr[-300:]!r}")
        return res


class DshRunner:
    """DSH headless：`dsh --profile headless "system + task"`。

    dsh CLI 接受单个任务描述字符串,无 --append-system-prompt;将 system 作为
    前置段与 prompt 合并成一条消息。无 stream-json → raw_jsonl 恒为 None(降级)。
    """

    name = "dsh"

    def run(
        self,
        system: str,
        prompt: str,
        *,
        timeout: Optional[int] = None,
        settings_path: Optional[str] = None,
        output_format: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> RunResult:
        combined = f"{system}\n\n# TASK\n{prompt}" if system else prompt
        # dsh 的 commander 会把以 `-` 开头的 argv 当选项（system 常以 YAML `---`
        # frontmatter 开头 → "error: unknown option '---'"）。前缀一个非 `-` 行规避。
        if combined.lstrip().startswith("-"):
            combined = "任务：\n" + combined
        cmd = ["dsh", "--profile", "headless", combined]
        res = _run_subprocess(cmd, timeout=timeout, cwd=cwd)
        if res.returncode not in (0, None):
            print(f"  ⚠️ dsh --profile headless 返回码 {res.returncode}，stderr={res.stderr[-300:]!r}")
        return res


_RUNNERS: dict = {
    "claude": ClaudeRunner,
    "cosight": CosightRunner,
    "codex": CodexRunner,
    "dsh": DshRunner,
}


def get_runner(name: Optional[str] = None):
    """返回 AgentRunner 实例（懒加载单实例）。

    优先级: 显式 name > env SKILLX_AGENT_CLI > 默认 'claude'。
    未知 runtime 名回退到 claude 并告警（防御性，不阻断）。
    """
    resolved = name or os.environ.get("SKILLX_AGENT_CLI", "").strip().lower() or "claude"
    cls = _RUNNERS.get(resolved)
    if cls is None:
        print(f"  ⚠️ 未知 agent runtime '{resolved}'，回退到 claude")
        cls = ClaudeRunner
        resolved = "claude"
    return cls()


def list_runners() -> Tuple[str, ...]:
    return RUNNER_NAMES


def runner_supports_stream_json(name: str) -> bool:
    """claude / cosight 支持 stream-json 工具审计流。"""
    return name in ("claude", "cosight")