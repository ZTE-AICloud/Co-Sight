#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单用例执行、resume 装配、端到端调度的测试。

全部通过 monkeypatch 掉 subprocess.Popen，不真的调用 claude CLI。
"""

import json
import subprocess
import uuid
from pathlib import Path

import pytest

import common
import config
from conftest import seed_record
from common import RunnerError
from run_tests import (
    _extract_partial_result,
    backfill_sessions,
    build_records,
    main,
    run_one_case,
)


# ============================== fake claude CLI ==============================

class FakeProc:
    """最小可用的 Popen 替身：communicate() 按剧本返回。"""

    def __init__(self, stdout="", stderr="", returncode=0, behavior=None,
                 record=None, timeout_for=None):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._behavior = behavior
        self._record = record if record is not None else {}
        self._timeout_for = timeout_for or set()
        self.killed = False
        self._fired = False

    def _should_timeout(self, prompt):
        if self._behavior == "timeout":
            return True
        return any(marker in str(prompt) for marker in self._timeout_for)

    def communicate(self, input=None, timeout=None):
        self._record.setdefault("prompts", []).append(input)
        self._record.setdefault("timeouts", []).append(timeout)
        # 只在首次带 timeout 的调用上超时；kill 之后的回收调用必须正常返回
        if timeout is not None and not self._fired and self._should_timeout(input):
            self._fired = True
            raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout)
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True
        self.returncode = -9

    def terminate(self):
        self.killed = True


def session_id_from(argv):
    """从 argv 里取 --session-id 的值（真实 CLI 也是这么拿的）。"""
    flag = config.CLAUDE_SESSION_ID_FLAG
    if flag in argv:
        index = argv.index(flag)
        if index + 1 < len(argv):
            return argv[index + 1]
    return ""


def write_fake_session_log(root, session_id, *, subagents=True):
    """照着真实 CLI 的落盘形态造一份假日志。

    真实形态是 `~/.*/projects/<cwd 编码>/<session_id>.jsonl` 加同名的
    `<session_id>/subagents/agent-*.jsonl` —— 主会话是文件、子代理是目录，
    两者同名，所以拷贝逻辑必须两种都认。
    """
    proj = Path(root) / "-fake-project"
    (proj / session_id / "subagents").mkdir(parents=True, exist_ok=True)
    (proj / f"{session_id}.jsonl").write_text('{"type":"user"}\n', encoding="utf-8")
    if subagents:
        (proj / session_id / "subagents" / "agent-abc.jsonl").write_text(
            '{"type":"assistant"}\n', encoding="utf-8")
    return proj


def install_fake_claude(monkeypatch, *, stdout="", stderr="", returncode=0,
                        behavior=None, capture=None, timeout_for=None,
                        session_root=None, write_session_log=True):
    """把 subprocess.Popen 换成替身，并抓取 cwd / env / argv。

    timeout_for: 命中其子串的 prompt 会走超时分支（用于混跑成功/超时）。
    session_root: 传了就让替身按 argv 里的 --session-id 落一份假会话日志，
        模拟真实 CLI 的行为；write_session_log=False 则只拿 id 不落盘
        （用于验证"日志找不到"的分支）。
    """
    capture = capture if capture is not None else {}
    calls = []

    def fake_popen(argv, **kwargs):
        calls.append({"argv": argv, "kwargs": kwargs})
        if session_root is not None and write_session_log:
            sid = session_id_from(argv)
            if sid:
                write_fake_session_log(session_root, sid)
        return FakeProc(stdout=stdout, stderr=stderr, returncode=returncode,
                        behavior=behavior, record=capture, timeout_for=timeout_for)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return calls, capture


def ok_stdout(result="检查完成，命中 1 处。"):
    return json.dumps({"type": "result", "result": result, "is_error": False})


def make_layout(tmp_path, *, seed_files=None):
    """铺一个合法的目录布局：产物目录与 agent_root 是**兄弟**目录。

    兄弟关系是硬要求——副本落在产物目录下，若产物目录在被测目录内部，复制会
    递归地把自己也复制进去。返回 (artifact_dir, agent_root)。
    """
    artifact_dir = tmp_path / "rd"
    agent_root = tmp_path / "agent"
    artifact_dir.mkdir(exist_ok=True)
    agent_root.mkdir(exist_ok=True)
    for rel, content in (seed_files or {"CLAUDE.md": "# 被测 agent\n"}).items():
        target = agent_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return artifact_dir, agent_root


# ============================== run_one_case ==============================

def test_run_one_case_success_writes_four_artifacts(tmp_path, monkeypatch):
    install_fake_claude(monkeypatch, stdout=ok_stdout("命中一处硬编码凭据"))
    case_dir, agent_root = make_layout(tmp_path)
    rec = seed_record()

    info = run_one_case(rec, 0, case_dir, agent_root)

    out = case_dir / "agent_functional_001"
    assert (out / "stdout.txt").is_file()
    assert (out / "stderr.txt").is_file()
    assert (out / "result.json").is_file()
    assert (out / "timing.json").is_file()

    assert info["status"] == "passed"
    assert info["exit_code"] == 0
    assert info["timed_out"] is False
    assert info["case_dir"] == str(out.resolve())
    assert "命中一处硬编码凭据" in info["result_preview"]


def test_run_one_case_feeds_input_on_stdin(tmp_path, monkeypatch):
    """只喂 input；precondition 不得出现在 prompt 里。"""
    calls, capture = install_fake_claude(monkeypatch, stdout=ok_stdout())
    case_dir, agent_root = make_layout(tmp_path)
    rec = seed_record(input="检查 ./demo_code",
                      precondition='DB_PASSWORD = "Admin@123";')

    run_one_case(rec, 0, case_dir, agent_root)

    assert capture["prompts"] == ["检查 ./demo_code"]
    assert "Admin@123" not in capture["prompts"][0]


def test_run_one_case_runs_in_per_case_workspace(tmp_path, monkeypatch):
    """cwd 是该用例自己的副本，不是共享的 agent_root——这正是隔离的落点。"""
    calls, _ = install_fake_claude(monkeypatch, stdout=ok_stdout())
    case_dir, agent_root = make_layout(tmp_path)

    info = run_one_case(seed_record(), 0, case_dir, agent_root)

    workspace = case_dir / "agent_functional_001" / "workspace"
    assert calls[0]["kwargs"]["cwd"] == str(workspace)
    assert calls[0]["kwargs"]["cwd"] != str(agent_root)
    assert info["workspace_dir"] == str(workspace.resolve())


def test_run_one_case_workspace_mirrors_agent_root(tmp_path, monkeypatch):
    """副本是源目录的完整拷贝，被测 agent 在自己的副本里能找到全部文件。"""
    install_fake_claude(monkeypatch, stdout=ok_stdout())
    case_dir, agent_root = make_layout(
        tmp_path, seed_files={"CLAUDE.md": "# 被测\n", "demo_code/a.py": "pwd = 'x'\n"})

    run_one_case(seed_record(), 0, case_dir, agent_root)

    workspace = case_dir / "agent_functional_001" / "workspace"
    assert (workspace / "CLAUDE.md").read_text(encoding="utf-8") == "# 被测\n"
    assert (workspace / "demo_code" / "a.py").read_text(encoding="utf-8") == "pwd = 'x'\n"


def test_run_one_case_does_not_write_back_to_agent_root(tmp_path, monkeypatch):
    """用例在副本里写文件，源目录必须一个字节都不变——这是隔离的核心断言。"""
    case_dir, agent_root = make_layout(tmp_path)
    before = common.sha256_tree(agent_root)

    def fake_popen(argv, **kwargs):
        # 模拟被测 agent 往 cwd 里写报告（正是上一轮串扰的来源）
        (kwargs["cwd"] and __import__("pathlib").Path(kwargs["cwd"]) / "report.md").write_text(
            "扫描结果\n", encoding="utf-8")
        return FakeProc(stdout=ok_stdout())

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    run_one_case(seed_record(), 0, case_dir, agent_root)

    assert common.sha256_tree(agent_root) == before
    assert not (agent_root / "report.md").exists()
    workspace = case_dir / "agent_functional_001" / "workspace"
    assert (workspace / "report.md").read_text(encoding="utf-8") == "扫描结果\n"


def test_run_one_case_stale_workspace_is_wiped(tmp_path, monkeypatch):
    """重跑时旧副本先被删掉：否则「重跑」会跑在上轮的残留上。"""
    install_fake_claude(monkeypatch, stdout=ok_stdout())
    case_dir, agent_root = make_layout(tmp_path)
    stale = case_dir / "agent_functional_001" / "workspace"
    stale.mkdir(parents=True)
    (stale / "上一轮留下的报告.md").write_text("stale", encoding="utf-8")

    run_one_case(seed_record(), 0, case_dir, agent_root)

    workspace = case_dir / "agent_functional_001" / "workspace"
    assert not (workspace / "上一轮留下的报告.md").exists()
    assert (workspace / "CLAUDE.md").is_file()


def test_run_one_case_rejects_workspace_inside_agent_root(tmp_path, monkeypatch):
    """产物目录落在被测目录内部会让复制无限递归，必须报错而非跑飞。"""
    install_fake_claude(monkeypatch, stdout=ok_stdout())
    agent_root = tmp_path / "agent"
    artifact_dir = agent_root / "outputs"
    artifact_dir.mkdir(parents=True)

    with pytest.raises(RunnerError, match="无限递归"):
        run_one_case(seed_record(), 0, artifact_dir, agent_root)


def test_run_one_case_sets_disable_mcp_env(tmp_path, monkeypatch):
    calls, _ = install_fake_claude(monkeypatch, stdout=ok_stdout())
    case_dir, agent_root = make_layout(tmp_path)
    run_one_case(seed_record(), 0, case_dir, agent_root)

    assert calls[0]["kwargs"]["env"]["CLAUDE_CODE_DISABLE_NONWHITELISTED_MCP"] == "1"


def test_run_one_case_passes_documented_cli_flags(tmp_path, monkeypatch):
    calls, _ = install_fake_claude(monkeypatch, stdout=ok_stdout())
    case_dir, agent_root = make_layout(tmp_path)
    run_one_case(seed_record(), 0, case_dir, agent_root)

    argv = calls[0]["argv"]
    assert argv[0] == "claude"
    assert "--output-format" in argv and "json" in argv
    assert "--permission-mode" in argv and "bypassPermissions" in argv
    # 该 flag 会让会话不落盘，日志拉取就永远落空——不能再出现
    assert "--no-session-persistence" not in argv
    assert "--session-id" in argv


def test_run_one_case_passes_a_distinct_uuid4_session_id(tmp_path, monkeypatch):
    """id 由 runner 预生成：每个用例一个新 uuid4，且不带重复。"""
    calls, _ = install_fake_claude(monkeypatch, stdout=ok_stdout())
    case_dir, agent_root = make_layout(tmp_path)

    run_one_case(seed_record("case_a"), 0, case_dir, agent_root)
    run_one_case(seed_record("case_b"), 0, case_dir, agent_root)

    ids = [session_id_from(c["argv"]) for c in calls]
    assert all(ids), "每个用例都必须带上 --session-id"
    uuid.UUID(ids[0], version=4)  # 非法 uuid4 会直接抛错
    uuid.UUID(ids[1], version=4)
    assert ids[0] != ids[1]


# ============================== 会话日志拉取 ==============================

def test_run_one_case_archives_session_log(tmp_path, monkeypatch, session_log_root):
    """日志拷到 <case_dir>/sessions/，绝对路径写进 run.session_dir。"""
    install_fake_claude(monkeypatch, stdout=ok_stdout(),
                        session_root=session_log_root)
    case_dir, agent_root = make_layout(tmp_path)

    info = run_one_case(seed_record(), 0, case_dir, agent_root)

    session_dir = case_dir / "agent_functional_001" / "sessions"
    assert info["session_dir"] == str(session_dir.resolve())
    assert config.RUN_SESSION_ERROR not in info
    # 主会话是文件、子代理是目录，两者同名且都要带过来
    assert (session_dir / f"{info['session_id']}.jsonl").is_file()
    assert (session_dir / info["session_id"] / "subagents" / "agent-abc.jsonl").is_file()


def test_run_one_case_records_missing_session_log(tmp_path, monkeypatch, session_log_root):
    """日志找不到时只记原因，不写 session_dir，更不改 status。"""
    install_fake_claude(monkeypatch, stdout=ok_stdout(),
                        session_root=session_log_root, write_session_log=False)
    case_dir, agent_root = make_layout(tmp_path)

    info = run_one_case(seed_record(), 0, case_dir, agent_root)

    assert info["session_error"] == "not_found"
    assert "session_dir" not in info
    assert info["session_id"]                      # id 照记，补拷时才认得出
    assert info["status"] == "passed"              # 基建故障不冤枉被测 Agent


def test_run_one_case_timeout_still_collects_session(tmp_path, monkeypatch, session_log_root):
    """超时拿不到 result（也就没有 id），但日志已落盘——预生成的 id 仍能找到它。

    这正是 id 必须由 runner 掌管的场合：靠 result 反推的话，最需要 trace 的用例
    反而一个日志都拿不到。
    """
    install_fake_claude(monkeypatch, behavior="timeout",
                        session_root=session_log_root)
    case_dir, agent_root = make_layout(tmp_path)

    info = run_one_case(seed_record(timeout=30), 0, case_dir, agent_root)

    assert info["status"] == "timeout"
    assert not (case_dir / "agent_functional_001" / "result.json").exists()
    assert info["session_dir"]
    assert (case_dir / "agent_functional_001" / "sessions"
            / f"{info['session_id']}.jsonl").is_file()


def test_run_one_case_cli_missing_still_records_session_id(tmp_path, monkeypatch,
                                                          session_log_root):
    """CLI 都不存在时也要留下 id 与失败原因，schema 才是一致的。"""
    def boom(*_a, **_kw):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(subprocess, "Popen", boom)
    case_dir, agent_root = make_layout(tmp_path)

    info = run_one_case(seed_record(), 0, case_dir, agent_root)

    assert info["status"] == "failed"
    assert info["session_id"]
    assert info["session_error"] == "not_found"


def test_run_one_case_wipes_stale_sessions(tmp_path, monkeypatch, session_log_root):
    """重跑是新的 session_id，旧日志必须先擦掉，否则目录里两份会话分不清。"""
    install_fake_claude(monkeypatch, stdout=ok_stdout(),
                        session_root=session_log_root)
    case_dir, agent_root = make_layout(tmp_path)
    stale = case_dir / "agent_functional_001" / "sessions"
    stale.mkdir(parents=True)
    (stale / "上一轮的会话.jsonl").write_text("stale", encoding="utf-8")

    info = run_one_case(seed_record(), 0, case_dir, agent_root)

    assert not (stale / "上一轮的会话.jsonl").exists()
    assert (stale / f"{info['session_id']}.jsonl").is_file()
    assert len(list(stale.glob("*.jsonl"))) == 1


def test_run_one_case_warns_when_reported_session_id_differs(tmp_path, monkeypatch,
                                                            session_log_root, capsys):
    """result 自报的 id 与预生成的不符要留痕——以预生成值为准（日志按它命名）。"""
    install_fake_claude(
        monkeypatch,
        stdout=json.dumps({"type": "result", "result": "done",
                           "session_id": "11111111-2222-3333-4444-555555555555"}),
        session_root=session_log_root)
    case_dir, agent_root = make_layout(tmp_path)

    info = run_one_case(seed_record(), 0, case_dir, agent_root)

    assert "session_id" in capsys.readouterr().err
    assert info["session_id"] != "11111111-2222-3333-4444-555555555555"


def test_run_one_case_honours_record_timeout(tmp_path, monkeypatch):
    _, capture = install_fake_claude(monkeypatch, stdout=ok_stdout())
    case_dir, agent_root = make_layout(tmp_path)
    run_one_case(seed_record(timeout=900), 0, case_dir, agent_root)
    assert capture["timeouts"] == [900]


def test_run_one_case_timeout_status(tmp_path, monkeypatch):
    """超时时进程是被 kill 的，没有自己的退出码，故 exit_code 为 null。"""
    install_fake_claude(monkeypatch, behavior="timeout")
    case_dir, agent_root = make_layout(tmp_path)

    info = run_one_case(seed_record(timeout=30), 0, case_dir, agent_root)

    assert info["status"] == "timeout"
    assert info["timed_out"] is True
    assert info["exit_code"] is None
    timing = json.loads((case_dir / "agent_functional_001" / "timing.json").read_text())
    assert set(timing) == {"elapsed_seconds", "exit_code", "timed_out"}
    assert timing["timed_out"] is True
    assert timing["exit_code"] is None


def test_run_one_case_nonzero_exit_is_failed(tmp_path, monkeypatch):
    install_fake_claude(monkeypatch, stdout="", stderr="boom", returncode=2)
    case_dir, agent_root = make_layout(tmp_path)

    info = run_one_case(seed_record(), 0, case_dir, agent_root)

    assert info["status"] == "failed"
    assert info["exit_code"] == 2
    assert (case_dir / "agent_functional_001" / "stderr.txt").read_text() == "boom"


def test_run_one_case_cli_missing(tmp_path, monkeypatch):
    def boom(*_a, **_kw):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(subprocess, "Popen", boom)
    case_dir, agent_root = make_layout(tmp_path)

    info = run_one_case(seed_record(), 0, case_dir, agent_root)

    assert info["status"] == "failed"
    assert info["exit_code"] == 127
    assert "not found" in (case_dir / "agent_functional_001" / "stderr.txt").read_text()


def test_run_one_case_empty_stdout_omits_result_json(tmp_path, monkeypatch):
    """stdout 为空时不产 result.json —— 空壳文件比缺席更误导。"""
    install_fake_claude(monkeypatch, stdout="", returncode=1)
    case_dir, agent_root = make_layout(tmp_path)
    run_one_case(seed_record(), 0, case_dir, agent_root)
    assert not (case_dir / "agent_functional_001" / "result.json").exists()


def test_run_one_case_unparseable_stdout_marks_parse_error(tmp_path, monkeypatch):
    install_fake_claude(monkeypatch, stdout="not json at all")
    case_dir, agent_root = make_layout(tmp_path)
    run_one_case(seed_record(), 0, case_dir, agent_root)

    payload = json.loads((case_dir / "agent_functional_001" / "result.json").read_text())
    assert payload["parse_error"] is True
    assert "not json" in payload["raw"]


def test_run_one_case_result_preview_is_full_text(tmp_path, monkeypatch):
    """preview 必须是 result 全文，不能有长度上限。"""
    long_result = "证据" * 3000  # 6000 字符，远超历史上的 400
    install_fake_claude(monkeypatch, stdout=ok_stdout(long_result))
    case_dir, agent_root = make_layout(tmp_path)

    info = run_one_case(seed_record(), 0, case_dir, agent_root)

    assert info["result_preview"] == long_result
    assert len(info["result_preview"]) == 6000


def test_run_one_case_result_preview_keeps_newlines(tmp_path, monkeypatch):
    """preview 不得折叠换行——下游裁判要看到原始排版。"""
    multi_line = "- 第一项\n- 第二项\n\n结论：通过"
    install_fake_claude(monkeypatch, stdout=ok_stdout(multi_line))
    case_dir, agent_root = make_layout(tmp_path)

    info = run_one_case(seed_record(), 0, case_dir, agent_root)

    assert info["result_preview"] == multi_line
    assert "\n" in info["result_preview"]


def test_run_one_case_non_string_result_is_serialized(tmp_path, monkeypatch):
    """result 非字符串时序列化，保证 preview 恒为 str，证据不静默丢失。"""
    structured = [{"step": 1, "ok": True}, {"step": 2, "ok": False}]
    install_fake_claude(
        monkeypatch,
        stdout=json.dumps({"type": "result", "result": structured}),
    )
    case_dir, agent_root = make_layout(tmp_path)

    info = run_one_case(seed_record(), 0, case_dir, agent_root)

    assert json.loads(info["result_preview"]) == structured


def test_run_one_case_truncated_json_salvages_result(tmp_path, monkeypatch):
    """超时截断的半截 JSON 里应能抢救出 result 文本。"""
    truncated = ('{"type":"result","result":"已完成前三步：抽取画像、归类能力点、'
                 '生成用例","usage":{"input_tokens":1234')
    install_fake_claude(monkeypatch, stdout=truncated)
    case_dir, agent_root = make_layout(tmp_path)
    info = run_one_case(seed_record(), 0, case_dir, agent_root)

    payload = json.loads((case_dir / "agent_functional_001" / "result.json").read_text())
    assert payload["partial_result"] is True
    assert payload["extracted_text"].startswith("已完成前三步")
    assert "已完成前三步" in info["result_preview"]


def test_run_one_case_salvage_has_no_length_cap(tmp_path, monkeypatch):
    """超时抢救出的 extracted_text 不设上限。"""
    salvaged = "已完成" * 1000  # 3000 字符，远超历史上的 1000
    # 手工拼半截 JSON：抢救逻辑匹配的是无空格的 `"result":"`
    truncated = '{"type":"result","result":"' + salvaged + '","usage":{"input_tokens":1234'
    install_fake_claude(monkeypatch, stdout=truncated)
    case_dir, agent_root = make_layout(tmp_path)
    info = run_one_case(seed_record(), 0, case_dir, agent_root)

    payload = json.loads((case_dir / "agent_functional_001" / "result.json").read_text())
    assert payload["partial_result"] is True
    assert payload["extracted_text"] == salvaged
    assert info["result_preview"] == salvaged


def test_run_one_case_parse_error_keeps_full_stdout(tmp_path, monkeypatch):
    """解析失败的 result.json.raw 与 preview 都保存完整的 stdout。"""
    raw = "not json at all\n" + "x" * 5000
    install_fake_claude(monkeypatch, stdout=raw)
    case_dir, agent_root = make_layout(tmp_path)
    info = run_one_case(seed_record(), 0, case_dir, agent_root)

    payload = json.loads((case_dir / "agent_functional_001" / "result.json").read_text())
    assert payload["parse_error"] is True
    assert payload["raw"] == raw
    assert info["result_preview"] == raw


# ============================== _extract_partial_result ==============================

def test_extract_partial_result_short_text():
    assert _extract_partial_result("tiny") == ""


def test_extract_partial_result_no_marker():
    assert _extract_partial_result("x" * 100) == ""


def test_extract_partial_result_handles_escaped_quote():
    text = '{"type":"result","result":"say \\"hi\\" now","usage":{"input_tokens":9'
    assert _extract_partial_result(text) == 'say \\"hi\\" now'


# ============================== build_records (resume) ==============================

def test_build_records_no_prior_file(tmp_path):
    records, skipped = build_records([seed_record()], tmp_path / "seed.jsonl")
    assert skipped == 0
    assert config.RUN_KEY not in records[0]


def test_build_records_skips_records_already_run(tmp_path):
    seed_path = tmp_path / "seed.jsonl"
    common.write_jsonl(seed_path, [
        {**seed_record("a"), "run": {"status": "passed"}},
        seed_record("b"),
    ])
    records, skipped = build_records([seed_record("a"), seed_record("b")], seed_path)
    assert skipped == 1
    assert records[0]["run"] == {"status": "passed"}
    assert config.RUN_KEY not in records[1]


def test_build_records_preserves_input_order(tmp_path):
    """输出顺序恒等于输入顺序，与 prior 文件里的顺序无关。"""
    seed_path = tmp_path / "seed.jsonl"
    common.write_jsonl(seed_path, [seed_record("a"), seed_record("b")])
    records, skipped = build_records([seed_record("a"), seed_record("b")], seed_path)
    assert skipped == 0
    assert [r["data_id"] for r in records] == ["a", "b"]


def test_build_records_merges_prior_run_value(tmp_path):
    seed_path = tmp_path / "seed.jsonl"
    common.write_jsonl(seed_path, [
        {**seed_record("a"), "run": {"status": "timeout"}},
        seed_record("b"),
    ])
    records, skipped = build_records([seed_record("a"), seed_record("b")], seed_path)
    assert skipped == 1
    assert records[0]["run"] == {"status": "timeout"}


def test_build_records_rejects_mismatched_input(tmp_path):
    """换了测试集却指向旧 run 目录时必须报错，不能把两份数据混在一起。"""
    seed_path = tmp_path / "seed.jsonl"
    common.write_jsonl(seed_path, [seed_record("a"), seed_record("b")])
    with pytest.raises(RunnerError, match="对不上"):
        build_records([seed_record("a"), seed_record("c")], seed_path)


def test_build_records_rejects_shorter_input(tmp_path):
    seed_path = tmp_path / "seed.jsonl"
    common.write_jsonl(seed_path, [seed_record("a"), seed_record("b")])
    with pytest.raises(RunnerError, match="续跑要求两次的用例集合完全一致"):
        build_records([seed_record("a")], seed_path)


# ============================== 端到端调度 ==============================

def _e2e_setup(make_seed_dir, tmp_path, n=3, **record_kw):
    """被测目录与 run 目录互不包含——副本落在 run 目录下，嵌套会让复制递归。"""
    root = tmp_path / "agent_root"
    root.mkdir(exist_ok=True)
    (root / "CLAUDE.md").write_text("# 被测 agent\n", encoding="utf-8")
    (root / "demo_code").mkdir(exist_ok=True)
    (root / "demo_code" / "app.properties").write_text(
        "db.password=Secret1\n", encoding="utf-8")
    records = [seed_record(f"agent_func_{i:03d}", **record_kw) for i in range(1, n + 1)]
    run_dir = make_seed_dir(records, agent_root=root)
    return run_dir, root, records


def test_main_end_to_end_writes_seed_and_cases(make_seed_dir, tmp_path, monkeypatch):
    run_dir, _root, _ = _e2e_setup(make_seed_dir, tmp_path, n=2)
    install_fake_claude(monkeypatch, stdout=ok_stdout())

    code = main(["--input", str(run_dir), "--concurrency", "2"])

    assert code == 0
    out = run_dir / "run_datasets"
    written = common.read_jsonl(out / "seed.jsonl")
    assert len(written) == 2
    for rec in written:
        assert rec["run"]["status"] == "passed"
        assert rec["run"]["case_dir"] == str(
            (out / rec["data_id"]).resolve()
        )
    assert (out / "agent_func_001" / "timing.json").is_file()
    assert (out / "agent_func_002" / "timing.json").is_file()


def test_main_defaults_output_to_input_run_dir(make_seed_dir, tmp_path, monkeypatch):
    run_dir, _root, _ = _e2e_setup(make_seed_dir, tmp_path, n=1)
    install_fake_claude(monkeypatch, stdout=ok_stdout())

    main(["--input", str(run_dir)])

    assert (run_dir / "run_datasets" / "seed.jsonl").is_file()
    # 生成产物原封不动
    assert (run_dir / "generated_datasets" / "seed.jsonl").is_file()


def test_main_never_modifies_input_seed(make_seed_dir, tmp_path, monkeypatch):
    run_dir, _root, _ = _e2e_setup(make_seed_dir, tmp_path, n=1)
    input_seed = run_dir / "generated_datasets" / "seed.jsonl"
    before = input_seed.read_text(encoding="utf-8")
    install_fake_claude(monkeypatch, stdout=ok_stdout())

    main(["--input", str(run_dir)])

    assert input_seed.read_text(encoding="utf-8") == before
    assert config.RUN_KEY not in before


def test_main_preserves_original_record_fields(make_seed_dir, tmp_path, monkeypatch):
    run_dir, _root, _ = _e2e_setup(make_seed_dir, tmp_path, n=1)
    install_fake_claude(monkeypatch, stdout=ok_stdout())
    main(["--input", str(run_dir)])

    rec = common.read_jsonl(run_dir / "run_datasets" / "seed.jsonl")[0]
    assert rec["kind"] == "seed"
    assert rec["dimension"] == "functional"
    assert rec["capability_ref"] == "C01"
    assert rec["precondition"]
    assert rec["expected_output"] == ["报告命中该 Java 源文件"]


def test_main_second_run_skips_completed(make_seed_dir, tmp_path, monkeypatch):
    run_dir, _root, _ = _e2e_setup(make_seed_dir, tmp_path, n=2)
    install_fake_claude(monkeypatch, stdout=ok_stdout())
    main(["--input", str(run_dir), "--concurrency", "2"])

    calls, _ = install_fake_claude(monkeypatch, stdout=ok_stdout("second"))
    code = main(["--input", str(run_dir), "--concurrency", "2"])

    assert code == 0
    assert calls == []  # 没有第二次真的调起 claude
    rec = common.read_jsonl(run_dir / "run_datasets" / "seed.jsonl")[0]
    assert "second" not in rec["run"]["result_preview"]


def test_main_resume_reruns_only_missing_case(make_seed_dir, tmp_path, monkeypatch):
    """删掉某个用例的 run 字段 + 目录，下一轮只补跑它。"""
    run_dir, _root, _ = _e2e_setup(make_seed_dir, tmp_path, n=2)
    install_fake_claude(monkeypatch, stdout=ok_stdout())
    main(["--input", str(run_dir), "--concurrency", "2"])

    out = run_dir / "run_datasets"
    records = common.read_jsonl(out / "seed.jsonl")
    del records[0]["run"]
    common.write_jsonl(out / "seed.jsonl", records)

    calls, _ = install_fake_claude(monkeypatch, stdout=ok_stdout("rerun"))
    main(["--input", str(run_dir)])

    assert len(calls) == 1
    assert "rerun" in common.read_jsonl(out / "seed.jsonl")[0]["run"]["result_preview"]


def test_main_concurrency_caps_in_flight(make_seed_dir, tmp_path, monkeypatch):
    """并发数 1 时不得出现交错（用活跃计数验证）。"""
    run_dir, _root, _ = _e2e_setup(make_seed_dir, tmp_path, n=4)
    state = {"active": 0, "peak": 0}
    lock = __import__("threading").Lock()

    def fake_popen(argv, **kwargs):
        class P(FakeProc):
            def communicate(self, input=None, timeout=None):
                with lock:
                    state["active"] += 1
                    state["peak"] = max(state["peak"], state["active"])
                try:
                    return ok_stdout(), ""
                finally:
                    with lock:
                        state["active"] -= 1
        return P()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    main(["--input", str(run_dir), "--concurrency", "1"])
    assert state["peak"] == 1


def test_main_returns_1_when_a_case_fails(make_seed_dir, tmp_path, monkeypatch):
    run_dir, _root, _ = _e2e_setup(make_seed_dir, tmp_path, n=2)
    install_fake_claude(monkeypatch, stdout="", stderr="nope", returncode=1)

    assert main(["--input", str(run_dir), "--concurrency", "2"]) == 1


def test_main_returns_1_when_a_case_times_out(make_seed_dir, tmp_path, monkeypatch):
    run_dir, _root, _ = _e2e_setup(make_seed_dir, tmp_path, n=1)
    install_fake_claude(monkeypatch, behavior="timeout")

    assert main(["--input", str(run_dir)]) == 1


def test_main_exit_code_covers_whole_seed(make_seed_dir, tmp_path, monkeypatch):
    """续跑时旧轮次的 timeout 仍应让退出码为 1，哪怕本轮跑的那条过了。"""
    root = tmp_path / "agent_root"
    root.mkdir()
    records = [
        seed_record("agent_func_001", input="TIMES_OUT 的用例"),
        seed_record("agent_func_002", input="正常的用例"),
    ]
    run_dir = make_seed_dir(records, agent_root=root)

    # 第一轮：001 超时，002 通过
    install_fake_claude(monkeypatch, stdout=ok_stdout(), timeout_for={"TIMES_OUT"})
    assert main(["--input", str(run_dir), "--concurrency", "2"]) == 1

    out = run_dir / "run_datasets"
    written = common.read_jsonl(out / "seed.jsonl")
    assert [r["run"]["status"] for r in written] == ["timeout", "passed"]

    # 第二轮：只补跑 001，这次它过了
    del written[0]["run"]
    common.write_jsonl(out / "seed.jsonl", written)
    install_fake_claude(monkeypatch, stdout=ok_stdout())
    assert main(["--input", str(run_dir)]) == 0

    # 第三轮：把 002 的旧结果改成 timeout → 退出码必须为 1
    written = common.read_jsonl(out / "seed.jsonl")
    written[1]["run"]["status"] = "timeout"
    common.write_jsonl(out / "seed.jsonl", written)
    install_fake_claude(monkeypatch, stdout=ok_stdout())
    assert main(["--input", str(run_dir)]) == 1


def test_main_rejects_output_that_overwrites_input_seed(make_seed_dir, tmp_path, monkeypatch):
    """--output 指向 --input 所在的 run_datasets 时会与输入 seed 撞车。"""
    run_dir, _root, _ = _e2e_setup(make_seed_dir, tmp_path, n=1)
    out = run_dir / "run_datasets"
    out.mkdir(parents=True)
    (out / "seed.jsonl").write_text(
        json.dumps(seed_record(), ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main(["--input", str(out / "seed.jsonl"), "--output", str(run_dir)])
    assert exc.value.code == 1


def test_main_rejects_concurrency_out_of_range(make_seed_dir, tmp_path):
    run_dir, _root, _ = _e2e_setup(make_seed_dir, tmp_path, n=1)
    with pytest.raises(SystemExit) as exc:
        main(["--input", str(run_dir), "--concurrency", "0"])
    assert exc.value.code == 1


def test_main_rejects_empty_seed(make_seed_dir, tmp_path):
    run_dir = make_seed_dir([], manifest=False)
    with pytest.raises(SystemExit) as exc:
        main(["--input", str(run_dir), "--agent", str(tmp_path)])
    assert exc.value.code == 1


def test_main_one_crash_does_not_abort_round(make_seed_dir, tmp_path, monkeypatch):
    """单用例抛异常不应带走整轮；该条记 failed，其余照跑。"""
    run_dir, _root, _ = _e2e_setup(make_seed_dir, tmp_path, n=2)

    def selective_popen(argv, **kwargs):
        # 第一条记录缺 input → run_one_case 抛 RunnerError
        raise RuntimeError("kaboom")

    monkeypatch.setattr(subprocess, "Popen", selective_popen)
    code = main(["--input", str(run_dir), "--concurrency", "2"])

    assert code == 1
    written = common.read_jsonl(run_dir / "run_datasets" / "seed.jsonl")
    assert len(written) == 2
    for rec in written:
        assert rec["run"]["status"] == "failed"
        assert "kaboom" in rec["run"]["error"]
        # 崩在复制阶段时副本可能没建成，但键必须存在，schema 才是一致的
        assert rec["run"]["workspace_dir"].endswith("/workspace")


# ============================== 会话日志（端到端 / 补拷） ==============================

def test_main_archives_every_session(make_seed_dir, tmp_path, monkeypatch, session_log_root):
    run_dir, _root, _ = _e2e_setup(make_seed_dir, tmp_path, n=3)
    install_fake_claude(monkeypatch, stdout=ok_stdout(),
                        session_root=session_log_root)

    assert main(["--input", str(run_dir), "--concurrency", "3"]) == 0

    out = run_dir / "run_datasets"
    for rec in common.read_jsonl(out / "seed.jsonl"):
        run = rec["run"]
        session_dir = Path(run["session_dir"])
        assert session_dir == (out / rec["data_id"] / "sessions").resolve()
        assert (session_dir / f"{run['session_id']}.jsonl").is_file()
    # 三条用例的会话彼此独立
    ids = [r["run"]["session_id"] for r in common.read_jsonl(out / "seed.jsonl")]
    assert len(set(ids)) == 3


def test_main_missing_sessions_do_not_change_exit_code(make_seed_dir, tmp_path,
                                                       monkeypatch, session_log_root,
                                                       capsys):
    """日志全丢时退出码仍为 0、status 仍是 passed，只在 stderr 汇总告警。"""
    run_dir, _root, _ = _e2e_setup(make_seed_dir, tmp_path, n=2)
    install_fake_claude(monkeypatch, stdout=ok_stdout(),
                        session_root=session_log_root, write_session_log=False)

    code = main(["--input", str(run_dir), "--concurrency", "2"])

    assert code == 0
    for rec in common.read_jsonl(run_dir / "run_datasets" / "seed.jsonl"):
        assert rec["run"]["status"] == "passed"
        assert rec["run"]["session_error"] == "not_found"
        assert "session_dir" not in rec["run"]
    err = capsys.readouterr().err
    assert "WARN" in err and "2 条用例没有拿到会话日志" in err


def test_main_backfills_session_for_skipped_record(make_seed_dir, tmp_path, monkeypatch,
                                                   session_log_root):
    """续跑时给"有 run 但缺 session_dir"的旧记录补拷日志。

    这是拷贝失败后的唯一补救路径：重跑整条要再花一次 API、答案还可能变，而日志
    本就躺在磁盘上。补拷只动会话三项——status / exit_code 是被测 Agent 的既成结果。
    """
    run_dir, _root, _ = _e2e_setup(make_seed_dir, tmp_path, n=1)
    install_fake_claude(monkeypatch, stdout=ok_stdout(),
                        session_root=session_log_root)
    main(["--input", str(run_dir)])

    # 把会话归档抹掉，模拟"上一轮没拷到"，status 保持不动
    out = run_dir / "run_datasets"
    records = common.read_jsonl(out / "seed.jsonl")
    session_id = records[0]["run"].pop("session_id")
    records[0]["run"].pop("session_dir")
    records[0]["run"]["session_error"] = "not_found"
    status_before = records[0]["run"]["status"]
    common.write_jsonl(out / "seed.jsonl", records)

    # 日志按 id 躺在磁盘上，但记录里已经没有钥匙了 → 补不了，且不动 status
    calls, _ = install_fake_claude(monkeypatch, stdout=ok_stdout("rerun"))
    assert main(["--input", str(run_dir)]) == 0
    assert calls == []
    rec = common.read_jsonl(out / "seed.jsonl")[0]
    assert rec["run"]["status"] == status_before
    assert "session_dir" not in rec["run"]

    # 补上钥匙（模拟拷贝失败但 id 已记下的情形）→ 下一轮续跑应把日志补回来
    records = common.read_jsonl(out / "seed.jsonl")
    records[0]["run"]["session_id"] = session_id
    common.write_jsonl(out / "seed.jsonl", records)

    assert main(["--input", str(run_dir)]) == 0
    rec = common.read_jsonl(out / "seed.jsonl")[0]
    assert rec["run"]["session_dir"]
    assert (Path(rec["run"]["session_dir"]) / f"{session_id}.jsonl").is_file()
    # 补拷不得改动执行结果
    assert rec["run"]["status"] == status_before
    assert "session_error" not in rec["run"]


def test_backfill_does_not_recopy_when_already_archived(make_seed_dir, tmp_path,
                                                        monkeypatch, session_log_root):
    run_dir, _root, _ = _e2e_setup(make_seed_dir, tmp_path, n=1)
    install_fake_claude(monkeypatch, stdout=ok_stdout(),
                        session_root=session_log_root)
    main(["--input", str(run_dir)])
    before = common.read_jsonl(run_dir / "run_datasets" / "seed.jsonl")[0]["run"]

    assert backfill_sessions(common.read_jsonl(
        run_dir / "run_datasets" / "seed.jsonl"), run_dir / "run_datasets") == (0, 0)
    after = common.read_jsonl(run_dir / "run_datasets" / "seed.jsonl")[0]["run"]
    assert after == before


def test_backfill_skips_legacy_records_without_session_id(make_seed_dir, tmp_path):
    """0.1.0 的旧记录没有 session_id（那一版日志压根没落盘），不猜、直接跳过。"""
    run_dir, _root, _ = _e2e_setup(make_seed_dir, tmp_path, n=1)
    records = common.read_jsonl(run_dir / "generated_datasets" / "seed.jsonl")
    records[0]["run"] = {"status": "passed", "exit_code": 0}

    assert backfill_sessions(records, run_dir / "run_datasets") == (0, 0)
    assert records[0]["run"] == {"status": "passed", "exit_code": 0}


# ============================== 隔离保证（端到端） ==============================

def test_main_leaves_agent_root_untouched(make_seed_dir, tmp_path, monkeypatch):
    """整轮跑完，被测目录必须一个字节都没变——串扰问题的最直接判据。"""
    run_dir, root, _ = _e2e_setup(make_seed_dir, tmp_path, n=3)
    before = common.sha256_tree(root)

    def writing_popen(argv, **kwargs):
        # 每个会话都往自己的 cwd 里写一份报告，模拟被测 agent 的正常产物
        Path(kwargs["cwd"], "plaintext-password-report.md").write_text(
            "扫描完成\n", encoding="utf-8")
        return FakeProc(stdout=ok_stdout())

    monkeypatch.setattr(subprocess, "Popen", writing_popen)
    assert main(["--input", str(run_dir), "--concurrency", "3"]) == 0

    assert common.sha256_tree(root) == before
    assert not (root / "plaintext-password-report.md").exists()


def test_main_cases_do_not_see_each_other(make_seed_dir, tmp_path, monkeypatch):
    """并发跑时每个会话只看到自己写的文件，看不到其他用例的产物。"""
    run_dir, _root, _ = _e2e_setup(make_seed_dir, tmp_path, n=3)
    observed = {}
    lock = __import__("threading").Lock()

    def writing_popen(argv, **kwargs):
        cwd = Path(kwargs["cwd"])
        with lock:
            observed[str(cwd)] = sorted(p.name for p in cwd.iterdir())
        (cwd / "report.md").write_text("x", encoding="utf-8")
        with lock:
            observed[str(cwd) + "#after"] = sorted(p.name for p in cwd.iterdir())
        return FakeProc(stdout=ok_stdout())

    monkeypatch.setattr(subprocess, "Popen", writing_popen)
    main(["--input", str(run_dir), "--concurrency", "3"])

    for key, names in observed.items():
        if key.endswith("#after"):
            continue
        assert "report.md" not in names, f"{key} 开局就看到了别的用例的产物"
    # 三个会话的 cwd 互不相同
    assert len({k for k in observed if not k.endswith("#after")}) == 3


def test_main_warns_when_agent_root_dirty_but_still_runs(make_seed_dir, tmp_path, monkeypatch, capsys):
    """源目录被写脏只告警、不阻断——用户可能是有意改了 agent 想重测。"""
    run_dir, root, _ = _e2e_setup(make_seed_dir, tmp_path, n=1)
    # 生成时刻的哈希（此时目录还干净），随后再写脏
    manifest_path = run_dir / "generated_datasets" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["agent_sha256"] = common.sha256_tree(root)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (root / "上一轮残留.md").write_text("dirty", encoding="utf-8")
    install_fake_claude(monkeypatch, stdout=ok_stdout())

    code = main(["--input", str(run_dir)])

    assert code == 0
    assert "WARN" in capsys.readouterr().err
    integrity = json.loads((run_dir / "run_datasets" / "run-manifest.json").read_text())
    assert integrity["matches"] is False
    assert integrity["isolation"] == "per-case-copy"
    assert integrity["agent_sha256_observed"]


def test_main_records_matching_hash_as_true(make_seed_dir, tmp_path, monkeypatch,
                                            capsys, session_log_root):
    """生成器 manifest 的哈希与实际一致时，记 matches=True 且不告警。"""
    run_dir, root, _ = _e2e_setup(make_seed_dir, tmp_path, n=1)
    manifest_path = run_dir / "generated_datasets" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["agent_sha256"] = common.sha256_tree(root)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    # 会话日志也归档到位，这样 stderr 上不该有任何告警
    install_fake_claude(monkeypatch, stdout=ok_stdout(),
                        session_root=session_log_root)

    code = main(["--input", str(run_dir)])

    assert code == 0
    assert "WARN" not in capsys.readouterr().err
    integrity = json.loads((run_dir / "run_datasets" / "run-manifest.json").read_text())
    assert integrity["matches"] is True


def test_main_rejects_output_inside_agent_root(make_seed_dir, tmp_path, monkeypatch):
    """产物目录落在被测目录内部会让副本递归复制自己，必须早失败。"""
    root = tmp_path / "agent_root"
    root.mkdir()
    run_dir = tmp_path / "ignored"
    run_dir.mkdir()
    records = [seed_record("agent_func_001")]
    make_seed_dir(records, run_name="ignored", agent_root=root)

    with pytest.raises(SystemExit) as exc:
        main(["--input", str(tmp_path / "ignored"), "--output", str(root / "out")])
    assert exc.value.code == 1
