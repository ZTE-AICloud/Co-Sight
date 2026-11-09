"""建 .drive/<plan_dir>/ 骨架 —— 只建目录，不写 state、不做编排决策。

拒绝覆盖既有工作是硬约束：用户已经跑过 drive 的目录，误建一次就可能抹掉
上次的规划与产物。

旧 .planning/ 检测 → 直接拒绝 + 提示 rm（drive runtime 不维护兼容代码）。
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from tests.roles import ds_init_planning as ip
from tests.script_loader import scripts_dir

SCRIPT = scripts_dir("startup") / "init_planning.py"
TEST_PLAN_DIR = "plan-test"
TEST_PLAN_DIR_PATH = f".drive/{TEST_PLAN_DIR}"


def _run_helper(*args):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True,
    )
    return proc.returncode, json.loads(proc.stdout)


class TestScaffold:
    def test_creates_drive_root(self, tmp_path):
        env = ip.init_planning(tmp_path, plan_dir=TEST_PLAN_DIR)
        assert env.ok
        assert (tmp_path / ".drive" / TEST_PLAN_DIR).is_dir()

    def test_creates_expected_subdirs(self, tmp_path):
        ip.init_planning(tmp_path, plan_dir=TEST_PLAN_DIR)
        for sub in ip.PLANNING_SUBDIRS:
            assert (tmp_path / ".drive" / TEST_PLAN_DIR / sub).is_dir(), f"缺子目录 {sub}"

    def test_reports_what_it_created(self, tmp_path):
        env = ip.init_planning(tmp_path, plan_dir=TEST_PLAN_DIR)
        assert TEST_PLAN_DIR_PATH in env.data["created"]
        assert len(env.data["created"]) == 1 + len(ip.PLANNING_SUBDIRS)

    def test_records_intent_when_given(self, tmp_path):
        env = ip.init_planning(tmp_path, plan_dir=TEST_PLAN_DIR, intent="重构 lib 层")
        assert env.data["intent_recorded"] is True
        text = (tmp_path / ".drive" / TEST_PLAN_DIR / ip.INTENT_FILENAME).read_text(encoding="utf-8")
        assert "重构 lib 层" in text

    def test_skips_intent_file_when_absent(self, tmp_path):
        env = ip.init_planning(tmp_path, plan_dir=TEST_PLAN_DIR)
        assert env.data["intent_recorded"] is False
        assert not (tmp_path / ".drive" / TEST_PLAN_DIR / ip.INTENT_FILENAME).exists()


class TestDoesNotTouchState:
    """写 state 是 state-machine skill 的职责，本脚本不碰。"""

    def test_no_execute_state_written(self, tmp_path):
        ip.init_planning(tmp_path, plan_dir=TEST_PLAN_DIR)
        assert not (tmp_path / ".drive" / TEST_PLAN_DIR / "executeState.json").exists()

    def test_no_state_md_written(self, tmp_path):
        ip.init_planning(tmp_path, plan_dir=TEST_PLAN_DIR)
        assert not (tmp_path / ".drive" / TEST_PLAN_DIR / "state.md").exists()

    def test_auto_mode_only_echoed_not_persisted(self, tmp_path):
        """auto_mode 原样回传给调用方，由其写入 state；本脚本不落盘。"""
        env = ip.init_planning(tmp_path, plan_dir=TEST_PLAN_DIR, auto_mode=True)
        assert env.data["auto_mode"] is True
        assert not (tmp_path / ".drive" / TEST_PLAN_DIR / "executeState.json").exists()


class TestRefusesToClobber:
    def test_rejects_plan_with_existing_files(self, tmp_path):
        plan_dir = tmp_path / ".drive" / TEST_PLAN_DIR
        plan_dir.mkdir(parents=True)
        (plan_dir / "manifest.md").write_text("既有规划", encoding="utf-8")

        env = ip.init_planning(tmp_path, plan_dir=TEST_PLAN_DIR)
        assert not env.ok
        assert env.reason == "already_exists"

    def test_preserves_existing_content_on_refusal(self, tmp_path):
        plan_dir = tmp_path / ".drive" / TEST_PLAN_DIR
        plan_dir.mkdir(parents=True)
        marker = plan_dir / "manifest.md"
        marker.write_text("既有规划", encoding="utf-8")

        ip.init_planning(tmp_path, plan_dir=TEST_PLAN_DIR)
        assert marker.read_text(encoding="utf-8") == "既有规划"

    def test_refusal_hint_explains_why(self, tmp_path):
        plan_dir = tmp_path / ".drive" / TEST_PLAN_DIR
        plan_dir.mkdir(parents=True)
        (plan_dir / "x.md").write_text("y", encoding="utf-8")

        env = ip.init_planning(tmp_path, plan_dir=TEST_PLAN_DIR)
        assert env.details.get("hint"), "拒绝时应有 hint 解释为何拒绝"

    def test_empty_dir_is_not_treated_as_existing(self, tmp_path):
        """空目录（或只有空子目录）不算既有工作，可以继续建。"""
        (tmp_path / ".drive" / TEST_PLAN_DIR / "inputs").mkdir(parents=True)
        env = ip.init_planning(tmp_path, plan_dir=TEST_PLAN_DIR)
        assert env.ok

    def test_force_overrides_refusal(self, tmp_path):
        plan_dir = tmp_path / ".drive" / TEST_PLAN_DIR
        plan_dir.mkdir(parents=True)
        (plan_dir / "x.md").write_text("y", encoding="utf-8")

        env = ip.init_planning(tmp_path, plan_dir=TEST_PLAN_DIR, force=True)
        assert env.ok


class TestLegacyPlanningRejected:
    """旧 .planning/ 数据拒绝继续 + 提示用户 rm。"""

    def test_legacy_planning_dir_is_rejected(self, tmp_path):
        legacy = tmp_path / ".planning"
        legacy.mkdir()
        (legacy / "manifest.md").write_text("旧规划", encoding="utf-8")

        env = ip.init_planning(tmp_path, plan_dir=TEST_PLAN_DIR)
        assert not env.ok
        assert env.reason == "legacy_planning_exists"

    def test_legacy_planning_hint_mentions_rm(self, tmp_path):
        legacy = tmp_path / ".planning"
        legacy.mkdir()
        (legacy / "manifest.md").write_text("旧规划", encoding="utf-8")

        env = ip.init_planning(tmp_path, plan_dir=TEST_PLAN_DIR)
        assert "rm" in env.details.get("hint", "")

    def test_legacy_planning_force_overrides(self, tmp_path):
        legacy = tmp_path / ".planning"
        legacy.mkdir()
        (legacy / "manifest.md").write_text("旧规划", encoding="utf-8")

        env = ip.init_planning(tmp_path, plan_dir=TEST_PLAN_DIR, force=True)
        assert env.ok


class TestErrors:
    def test_missing_work_dir_is_rejected(self, tmp_path):
        env = ip.init_planning(tmp_path / "nope", plan_dir=TEST_PLAN_DIR)
        assert not env.ok
        assert env.reason == "invalid_arg"

    def test_missing_plan_dir_is_rejected(self, tmp_path):
        env = ip.init_planning(tmp_path, plan_dir="")
        assert not env.ok
        assert env.reason == "missing_plan_dir"

    def test_unwritable_parent_reports_reason(self, tmp_path):
        target = tmp_path / "locked"
        target.mkdir()
        target.chmod(0o500)
        try:
            env = ip.init_planning(target, plan_dir=TEST_PLAN_DIR)
            assert not env.ok
            assert env.reason == "write_failed"
            assert env.details["hint"]
        finally:
            target.chmod(0o700)


class TestCLI:
    def _run(self, *args: str):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), *args], capture_output=True, text=True
        )
        return proc.returncode, json.loads(proc.stdout)

    def test_cli_creates_and_exits_zero(self, tmp_path):
        code, payload = self._run("--work-dir", str(tmp_path), "--plan-dir", TEST_PLAN_DIR)
        assert code == 0
        assert payload["ok"] is True

    def test_cli_exits_one_on_existing(self, tmp_path):
        plan_dir = tmp_path / ".drive" / TEST_PLAN_DIR
        plan_dir.mkdir(parents=True)
        (plan_dir / "a.md").write_text("x", encoding="utf-8")
        code, payload = self._run("--work-dir", str(tmp_path), "--plan-dir", TEST_PLAN_DIR)
        assert code == 1
        assert payload["reason"] == "already_exists"

    def test_cli_passes_intent_through(self, tmp_path):
        code, payload = self._run(
            "--work-dir", str(tmp_path), "--plan-dir", TEST_PLAN_DIR, "--intent", "做点事"
        )
        assert code == 0
        assert payload["data"]["intent_recorded"] is True

    def test_cli_auto_flag_echoed(self, tmp_path):
        _, payload = self._run(
            "--work-dir", str(tmp_path), "--plan-dir", TEST_PLAN_DIR, "--auto"
        )
        assert payload["data"]["auto_mode"] is True

    def test_cli_missing_plan_dir_exits_one(self, tmp_path):
        code, payload = self._run("--work-dir", str(tmp_path))
        assert code == 1
        assert payload["reason"] == "missing_plan_dir"

    def test_cli_plan_and_dir_mutually_exclusive(self, tmp_path):
        code, payload = self._run(
            "--work-dir", str(tmp_path),
            "--plan-name", "foo",
            "--plan-dir", "plan-20260817-1530-foo",
        )
        assert code == 1


class TestPlanNameValidation:
    def test_construct_plan_dir_format(self):
        d = ip.construct_plan_dir("add-user-auth", ts="20260817-1530")
        assert d == "plan-20260817-1530-add-user-auth"

    def test_construct_plan_dir_uses_utc_when_no_ts(self):
        import re
        d = ip.construct_plan_dir("foo")
        # plan-<12chars-ts>-foo
        assert re.fullmatch(r"^plan-\d{8}-\d{4}-foo$", d)

    @pytest.mark.parametrize(
        "name,ok",
        [
            ("add-user-auth", True),
            ("fix-import-deadlock", True),
            ("migrate-to-v2", True),
            ("a", True),
            ("a-b-c-d", True),
            ("Foo", False),         # 大写
            ("-foo", False),       # 开头 -
            ("foo-", False),       # 结尾 -
            ("foo_bar", False),    # 含 _
            ("foo bar", False),    # 含空格
            ("", False),
            (".", False),
            ("..", False),
            ("a" * 65, False),     # 超过 64 字符
        ],
    )
    def test_validate_plan_name(self, name, ok):
        passed, _ = ip.validate_plan_name(name)
        assert passed is ok


class TestPlanNameAutoConstruction:
    def test_cli_plan_name_creates_ts_prefixed_dir(self, tmp_path):
        code, payload = _run_helper(
            "--work-dir", str(tmp_path),
            "--plan-name", "add-user-auth",
        )
        assert code == 0, payload
        expected_dir = ip.construct_plan_dir("add-user-auth")
        assert payload["data"]["plan_dir"] == expected_dir
        assert payload["data"]["plan_name"] == "add-user-auth"
        assert (tmp_path / ".drive" / expected_dir).is_dir()

    def test_cli_plan_name_writes_current_plan_marker(self, tmp_path):
        code, payload = _run_helper(
            "--work-dir", str(tmp_path),
            "--plan-name", "foo",
        )
        assert code == 0, payload
        marker = tmp_path / ".drive" / ".current-plan"
        assert marker.is_file()
        assert marker.read_text(encoding="utf-8").startswith("plan-")

    def test_cli_plan_name_collision(self, tmp_path):
        # 建第一个 plan
        _run_helper("--work-dir", str(tmp_path), "--plan-name", "foo")
        # 立即再建同名的——撞了 fail-fast
        code, payload = _run_helper(
            "--work-dir", str(tmp_path),
            "--plan-name", "foo",
        )
        assert code == 1
        assert payload["reason"] == "already_exists"

    def test_cli_plan_name_invalid(self, tmp_path):
        code, payload = _run_helper(
            "--work-dir", str(tmp_path),
            "--plan-name", "Foo Bar",
        )
        assert code == 1
        assert payload["reason"] == "invalid_plan_name"


class TestRunMeta:
    def test_run_meta_contains_all_fields(self, tmp_path):
        # 通过 git init + commit 让 _detect_git_branch / _detect_git_head 真实工作
        import subprocess as _sp
        _sp.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
        _sp.run(["git", "config", "user.email", "t@t"], cwd=str(tmp_path), check=True)
        _sp.run(["git", "config", "user.name", "t"], cwd=str(tmp_path), check=True)
        (tmp_path / "f").write_text("x", encoding="utf-8")
        _sp.run(["git", "add", "f"], cwd=str(tmp_path), check=True)
        _sp.run(["git", "commit", "-q", "-m", "init"], cwd=str(tmp_path), check=True)
        _sp.run(["git", "checkout", "-q", "-b", "main-dev"], cwd=str(tmp_path), check=True)

        code, payload = _run_helper(
            "--work-dir", str(tmp_path),
            "--plan-name", "add-user-auth",
            "--intent", "add auth",
        )
        assert code == 0
        run_meta = payload["data"]["run_meta"]
        assert run_meta["schema_version"] == "drive.runtime.run_meta.v1"
        assert run_meta["plan_name"] == "add-user-auth"
        assert run_meta["plan_dir"].startswith("plan-") and "add-user-auth" in run_meta["plan_dir"]
        # git_head 应是真实 commit SHA（40 hex）
        assert isinstance(run_meta["git_head"], str) and len(run_meta["git_head"]) == 40
        assert run_meta["git_branch"] == "main-dev"
        assert run_meta["worktree"] == str(tmp_path.resolve())

    def test_workflow_hash_matches_content_sha256(self, tmp_path):
        import hashlib
        (tmp_path / "workflow.yaml").write_text("phases: []\n", encoding="utf-8")
        code, payload = _run_helper(
            "--work-dir", str(tmp_path),
            "--plan-name", "foo",
        )
        assert code == 0
        expected = "sha256:" + hashlib.sha256(
            (tmp_path / "workflow.yaml").read_bytes()
        ).hexdigest()
        assert payload["data"]["run_meta"]["workflow_hash"] == expected

    def test_workflow_hash_missing_when_no_workflow_yaml(self, tmp_path):
        code, payload = _run_helper(
            "--work-dir", str(tmp_path),
            "--plan-name", "foo",
        )
        assert code == 0
        assert payload["data"]["run_meta"].get("workflow_hash") is None

    def test_run_meta_uses_content_sha256_not_filename(self, tmp_path):
        """rename workflow.yaml 后找不到，workflow_hash 应为 None。"""
        (tmp_path / "workflow.yaml").write_text("phases: []\n", encoding="utf-8")
        # 改名重跑
        (tmp_path / "workflow.yaml").rename(tmp_path / "workflow-renamed.yaml")
        code, payload = _run_helper(
            "--work-dir", str(tmp_path),
            "--plan-name", "foo",
        )
        assert code == 0
        # 现在 workflow_hash 应为 None（找不到 workflow.yaml）
        assert payload["data"]["run_meta"].get("workflow_hash") is None