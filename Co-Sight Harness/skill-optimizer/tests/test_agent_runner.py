"""AgentRunner 三 provider 单元测试。

用伪造 CLI stub（PATH 上真实的 claude/codex/dsh 不可用，也绝不应调用真实 agent）：
每个 stub 把收到的 argv 写入 `FAKE_AGENT_LOG`，并回显约定的 stdout，便于断言：

- ClaudeRunner：命令构造（claude -p / --append-system-prompt / --allowedTools 默认 /
  --dangerously-skip-permissions）、stream-json result 帧解析、text 模式回退。
- CodexRunner：临时 AGENTS.md 注入 system + `codex exec -C` 命令构造；raw_jsonl=None。
- DshRunner：`dsh --profile headless` + system 与 prompt 合并；raw_jsonl=None。
- get_runner：显式 name > env SKILLX_AGENT_CLI > 默认 claude 的优先级。
"""
import json
import os
import subprocess

import pytest

try:
    import agent_runner as ar
except ImportError:
    # 测试时 scripts/ 不在 sys.path 的场景（pytest 根目录运行）
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import agent_runner as ar


# ─── 伪 CLI stub 生成 ──────────────────────────────────────────────────────

_CLAUDE_STUB = """#!/usr/bin/env python3
import sys, os, json
log = os.environ["FAKE_AGENT_LOG"]
with open(log, "a") as f:
    json.dump([os.path.basename(sys.argv[0])] + sys.argv[1:], f); f.write("\\n")
args = sys.argv[1:]
if "--output-format" in args:
    i = args.index("--output-format")
    if args[i + 1] == "stream-json":
        print(json.dumps({"type": "result", "result": "RESULT_FINAL"}))
        sys.exit(0)
sys.argv[0] = "fake-tools-claude"  # 防止占位替换
print("TEXT_OUTPUT_NO_JSON")
"""

_CODEX_STUB = """#!/usr/bin/env python3
import sys, os, json
log = os.environ["FAKE_AGENT_LOG"]
with open(log, "a") as f:
    json.dump([os.path.basename(sys.argv[0])] + sys.argv[1:], f); f.write("\\n")
# codex 以 -C <workdir> 定位 AGENTS.md：读出来 append 到 log，供测试断言 system 注入
if "-C" in sys.argv:
    i = sys.argv.index("-C")
    work = sys.argv[i + 1]
    ag = os.path.join(work, "AGENTS.md")
    if os.path.exists(ag):
        content = open(ag, encoding="utf-8").read()
        with open(log, "a") as f:
            json.dump({"__agents_md": content}, f); f.write("\\n")
print("CODEX_OUTPUT")
"""

_DSH_STUB = """#!/usr/bin/env python3
import sys, os, json
log = os.environ["FAKE_AGENT_LOG"]
with open(log, "a") as f:
    json.dump([os.path.basename(sys.argv[0])] + sys.argv[1:], f); f.write("\\n")
print("DSH_OUTPUT")
"""


@pytest.fixture
def fake_bins(tmp_path, monkeypatch):
    """生成三个可执行 stub 目录，并把其前置到 PATH，同时设 FAKE_AGENT_LOG。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.jsonl"
    for name, code in (
        ("claude", _CLAUDE_STUB),
        ("cosight", _CLAUDE_STUB),  # cosight 命令面与 claude 同构，复用同一 stub
        ("codex", _CODEX_STUB),
        ("dsh", _DSH_STUB),
    ):
        p = bin_dir / name
        p.write_text(code, encoding="utf-8")
        p.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_AGENT_LOG", str(log))
    return log


def _read_log(log):
    calls = []
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    calls.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return calls


# ─── ClaudeRunner ─────────────────────────────────────────────────────────


def test_claude_runner_command_and_text(fake_bins, monkeypatch, tmp_path):
    log = fake_bins
    monkeypatch.setenv("SKILLX_AGENT_CURRENT", "")  # 无关
    runner = ar.get_runner("claude")
    res = runner.run("THE_SYSTEM", "THE_PROMPT", cwd=str(tmp_path))
    calls = _read_log(log)
    assert calls, "应记录了 claude 调用"
    argv = calls[0]
    assert argv[0] == "claude"
    assert argv[1] == "-p"
    assert argv[2] == "THE_PROMPT"
    assert "--append-system-prompt" in argv
    assert argv[argv.index("--append-system-prompt") + 1] == "THE_SYSTEM"
    assert "--allowedTools" in argv
    assert "--dangerously-skip-permissions" in argv
    assert res.returncode == 0
    assert res.stdout == "TEXT_OUTPUT_NO_JSON"
    assert res.raw_jsonl is None


def test_claude_runner_stream_json_parse(fake_bins, tmp_path):
    log = fake_bins
    runner = ar.get_runner("claude")
    res = runner.run("S", "P", output_format="stream-json", cwd=str(tmp_path))
    assert res.stdout == "RESULT_FINAL", "stream-json 应把最末 result 帧作为最终文本"
    assert res.raw_jsonl is not None
    assert '"type": "result"' in res.raw_jsonl or '"type": "result"' in res.raw_jsonl


def test_claude_runner_respects_off_env(fake_bins, monkeypatch, tmp_path):
    log = fake_bins
    monkeypatch.setenv("SKILLX_AGENT_ALLOWED_TOOLS_OFF", "1")
    monkeypatch.setenv("SKILLX_AGENT_SKIP_PERMISSIONS_OFF", "1")
    runner = ar.get_runner("claude")
    runner.run("S", "P", cwd=str(tmp_path))
    argv = _read_log(log)[0]
    assert "--allowedTools" not in argv
    assert "--dangerously-skip-permissions" not in argv


def test_claude_runner_timeout_captured(fake_bins, monkeypatch):
    # 用极短 timeout + 让 stub sleep，验证超时进入 exception_str 且不抛异常
    log = fake_bins
    bin_dir = log.parent / "bin"
    slow = bin_dir / "claude"
    slow.write_text(
        "#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n", encoding="utf-8"
    )
    slow.chmod(0o755)
    runner = ar.get_runner("claude")
    res = runner.run("S", "P", timeout=1)
    assert res.exception_str is not None
    assert "TimeoutExpired" in res.exception_str
    assert res.returncode is None


# ─── CosightRunner ────────────────────────────────────────────────────────


def test_cosight_runner_command_and_stream_json(fake_bins, tmp_path):
    """CosightRunner 复用 ClaudeRunner 命令构造：cosight -p + append-system-prompt，
    stream-json 工具审计流与 claude 一致（raw_jsonl 支持）。"""
    log = fake_bins
    runner = ar.get_runner("cosight")
    res = runner.run("COSIGHT_SYSTEM", "COSIGHT_PROMPT", output_format="stream-json", cwd=str(tmp_path))
    calls = _read_log(log)
    argv = calls[0]
    assert argv[0] == "cosight", "binary 应为 cosight"
    assert argv[1] == "-p"
    assert argv[2] == "COSIGHT_PROMPT"
    assert "--append-system-prompt" in argv
    assert argv[argv.index("--append-system-prompt") + 1] == "COSIGHT_SYSTEM"
    assert "--allowedTools" in argv
    assert "--dangerously-skip-permissions" in argv
    assert res.returncode == 0
    assert res.stdout == "RESULT_FINAL", "cosight 应支持 stream-json result 帧"
    assert res.raw_jsonl is not None


def test_cosight_runner_text_mode(fake_bins, tmp_path):
    log = fake_bins
    runner = ar.get_runner("cosight")
    res = runner.run("S", "P", cwd=str(tmp_path))
    assert _read_log(log)[0][0] == "cosight"
    assert res.stdout == "TEXT_OUTPUT_NO_JSON"
    assert res.raw_jsonl is None


def test_load_project_settings_env(tmp_path, monkeypatch):
    """_load_project_settings_env 向上找项目 .cosight/settings.json 的 env 段。"""
    proj = tmp_path / "proj"
    (proj / ".cosight").mkdir(parents=True)
    (proj / ".cosight" / "settings.json").write_text(
        json.dumps({"env": {"COSIGHT_ROUTER_ENABLED": "false", "FOO_PROJECT": "BAR"}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(proj)
    env = ar._load_project_settings_env()
    assert env.get("COSIGHT_ROUTER_ENABLED") == "false"
    assert env.get("FOO_PROJECT") == "BAR"


def test_load_project_settings_env_empty_without_cosight(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert ar._load_project_settings_env() == {}


def test_cosight_runner_injects_env_via_process(tmp_path, monkeypatch):
    """用能回显 env 的 stub 精确验证 COSIGHT_ROUTER_ENABLED / COSIGHT_LOG_LEVEL 进入子进程。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.jsonl"
    stub = bin_dir / "cosight"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import os, json\n"
        "print(os.environ.get('COSIGHT_ROUTER_ENABLED',''))\n"
        "print(os.environ.get('COSIGHT_LOG_LEVEL',''))\n"
        "print(os.environ.get('SKILLX_MARKER',''))\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_AGENT_LOG", str(log))
    proj = tmp_path / "proj"
    (proj / ".cosight").mkdir(parents=True)
    (proj / ".cosight" / "settings.json").write_text(
        json.dumps({"env": {"COSIGHT_ROUTER_ENABLED": "false"}}), encoding="utf-8"
    )
    monkeypatch.chdir(proj)
    res = ar.get_runner("cosight").run("S", "P", cwd=str(proj))
    lines = res.stdout.splitlines()
    assert lines[0] == "false", "项目 env COSIGHT_ROUTER_ENABLED=false 应注入 cosight 子进程"
    assert lines[1] == "warn", "COSIGHT_LOG_LEVEL 应置 warn"
    # 无关 env（SKILLX_MARKER 未设）不注入；其空值 print 因 RunResult 整体 .strip 被收敛，
    # 因此只应恰好 2 行（false + warn），无泄漏的第三行。
    assert len(lines) == 2, f"不应注入无关 env，实际行数 {len(lines)}: {lines!r}"


# ─── CodexRunner ──────────────────────────────────────────────────────────


def test_codex_runner_injects_agents_md_and_command(fake_bins, tmp_path):
    log = fake_bins
    runner = ar.get_runner("codex")
    res = runner.run("CODEX_SYSTEM", "CODEX_PROMPT", cwd=str(tmp_path))
    calls = _read_log(log)
    argv = calls[0]
    assert argv[0] == "codex"
    assert argv[1] == "exec"
    assert argv[2] == "-C"
    workdir = argv[3]
    assert "--skip-git-repo-check" in argv
    assert "--allow-tools" in argv
    assert "--sandbox" in argv
    assert argv[-1] == "CODEX_PROMPT", "prompt 应作为最后一个位置参数"
    # 断言 system 经 AGENTS.md 注入（stub 已把 AGENTS.md 内容写回 log）
    agents = [c for c in calls[1:] if isinstance(c, dict) and "__agents_md" in c]
    assert agents, "stub 应已确认 AGENTS.md 存在"
    assert agents[0]["__agents_md"] == "CODEX_SYSTEM"
    assert res.returncode == 0
    assert res.raw_jsonl is None, "codex 不支持 stream-json，raw_jsonl 恒为 None"


# ─── DshRunner ────────────────────────────────────────────────────────────


def test_dsh_runner_combines_system_and_prompt(fake_bins, tmp_path):
    log = fake_bins
    runner = ar.get_runner("dsh")
    res = runner.run("DSH_SYSTEM", "DSH_PROMPT", cwd=str(tmp_path))
    argv = _read_log(log)[0]
    assert argv[0] == "dsh"
    assert argv[1] == "--profile"
    assert argv[2] == "headless"
    combined = argv[3]
    assert combined.startswith("DSH_SYSTEM"), "system 应作为前置段"
    assert "# TASK" in combined
    assert "DSH_PROMPT" in combined
    assert res.returncode == 0
    assert res.stdout == "DSH_OUTPUT"
    assert res.raw_jsonl is None


def test_dsh_runner_without_system(fake_bins, tmp_path):
    log = fake_bins
    runner = ar.get_runner("dsh")
    runner.run("", "ONLY_PROMPT", cwd=str(tmp_path))
    argv = _read_log(log)[0]
    assert argv[3] == "ONLY_PROMPT", "无 system 时不应附加 # TASK 段"


# ─── get_runner 选择优先级 ────────────────────────────────────────────────


def test_get_runner_defaults_to_claude(monkeypatch):
    monkeypatch.delenv("SKILLX_AGENT_CLI", raising=False)
    assert ar.get_runner().__class__ is ar.ClaudeRunner


def test_get_runner_uses_env(monkeypatch):
    monkeypatch.setenv("SKILLX_AGENT_CLI", "codex")
    assert ar.get_runner().__class__ is ar.CodexRunner


def test_get_runner_uses_cosight_env(monkeypatch):
    monkeypatch.setenv("SKILLX_AGENT_CLI", "cosight")
    assert ar.get_runner().__class__ is ar.CosightRunner


def test_get_runner_explicit_overrides_env(monkeypatch):
    monkeypatch.setenv("SKILLX_AGENT_CLI", "codex")
    assert ar.get_runner("dsh").__class__ is ar.DshRunner


def test_get_runner_unknown_falls_back_to_claude(monkeypatch, capsys):
    monkeypatch.delenv("SKILLX_AGENT_CLI", raising=False)
    assert ar.get_runner("bogus").__class__ is ar.ClaudeRunner
    assert "回退" in capsys.readouterr().out


def test_runner_supports_stream_json_claude_and_cosight():
    assert ar.runner_supports_stream_json("claude") is True
    assert ar.runner_supports_stream_json("cosight") is True
    assert ar.runner_supports_stream_json("codex") is False
    assert ar.runner_supports_stream_json("dsh") is False
    assert ar.list_runners() == ("claude", "cosight", "codex", "dsh")