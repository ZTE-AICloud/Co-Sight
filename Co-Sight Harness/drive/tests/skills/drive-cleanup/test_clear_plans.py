"""clear_plans.py 单元测试 —— 默认行为 / keep / all / names / running 跳过 / tar 备份。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
CLEAR_PLANS = PLUGIN_ROOT / "skills" / "drive-cleanup" / "scripts" / "clear_plans.py"


def _make_plan(work_dir: Path, name: str, *, mtime_minutes_ago: int = 60) -> Path:
    """建一个带 stub 内容的 plan 目录。mtime_minutes_ago 越大越"老"。"""
    plan_dir = work_dir / ".drive" / name
    plan_dir.mkdir(parents=True)
    (plan_dir / "manifest.md").write_text("# manifest\n", encoding="utf-8")
    (plan_dir / "taskRecord.yaml").write_text("plan_id: t\n", encoding="utf-8")
    if mtime_minutes_ago > 0:
        old_time = time.time() - mtime_minutes_ago * 60
        os.utime(plan_dir, (old_time, old_time))
    return plan_dir


def _run(args: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        [sys.executable, str(CLEAR_PLANS), *args],
        capture_output=True, text=True,
    )
    return proc


def _result_from_stdout(proc: subprocess.CompletedProcess) -> dict:
    """从 stdout 末尾的 JSON 块解出 Envelope。

    clear_plans 顺序输出 preview 多行 + JSON 缩进块。找第一个 `{` 起到末尾。
    """
    text = proc.stdout
    start = text.find("{")
    if start < 0:
        return json.loads(text)  # 可能是 {"ok": ...} 单行
    return json.loads(text[start:])


class TestDefaultBehavior:
    def test_default_clears_oldest_10(self, tmp_path):
        for i in range(15):
            _make_plan(tmp_path, f"plan-20260817-153{i:02d}-foo{i:02d}")
        proc = _run(["--work-dir", str(tmp_path)])
        assert proc.returncode == 1, "dry-run default 应 exit 1（needs_confirmation）"
        result = _result_from_stdout(proc)
        assert result["reason"] == "needs_confirmation"
        assert len(result["would_clear"]) == 10
        # 默认 10 个是最早的（mtime 最小）
        first_cleared = result["would_clear"][0]
        assert first_cleared.endswith("foo00")

    def test_force_executes_default(self, tmp_path):
        _make_plan(tmp_path, "plan-20260817-1530-old", mtime_minutes_ago=60)
        _make_plan(tmp_path, "plan-20260817-1531-mid", mtime_minutes_ago=30)
        proc = _run(["--work-dir", str(tmp_path), "--force"])
        assert proc.returncode == 0
        result = _result_from_stdout(proc)
        assert result["ok"] is True
        # 只有 2 个 plan，默认清理最早的 10 个——所以清这 2 个
        assert len(result["data"]["cleared"]) == 2
        cleared_names = {c["plan"] for c in result["data"]["cleared"]}
        assert cleared_names == {"plan-20260817-1530-old", "plan-20260817-1531-mid"}
        assert not (tmp_path / ".drive" / "plan-20260817-1530-old").exists()


class TestKeep:
    def test_keep_n_keeps_newest(self, tmp_path):
        for i in range(5):
            _make_plan(tmp_path, f"plan-20260817-153{i}-bar{i}", mtime_minutes_ago=10 * (5 - i))
        proc = _run(["--work-dir", str(tmp_path), "--keep", "2", "--force"])
        assert proc.returncode == 0
        result = _result_from_stdout(proc)
        cleared_names = {c["plan"] for c in result["data"]["cleared"]}
        assert len(cleared_names) == 3  # 5 - 2
        # 保留最新 2 个
        assert (tmp_path / ".drive" / "plan-20260817-1534-bar4").exists()
        assert (tmp_path / ".drive" / "plan-20260817-1533-bar3").exists()

    def test_keep_larger_than_count_does_nothing(self, tmp_path):
        _make_plan(tmp_path, "plan-20260817-1530-a")
        _make_plan(tmp_path, "plan-20260817-1531-b")
        proc = _run(["--work-dir", str(tmp_path), "--keep", "10", "--force"])
        assert proc.returncode == 0
        result = _result_from_stdout(proc)
        assert result["data"]["cleared"] == []


class TestAll:
    def test_all_clears_everything(self, tmp_path):
        for i in range(3):
            _make_plan(tmp_path, f"plan-20260817-153{i}-a{i}")
        proc = _run(["--work-dir", str(tmp_path), "--all", "--force"])
        assert proc.returncode == 0
        result = _result_from_stdout(proc)
        assert len(result["data"]["cleared"]) == 3
        # .drive/ 下不应再有 plan-* 子目录
        remaining = list((tmp_path / ".drive").glob("plan-*"))
        assert remaining == []


class TestNames:
    def test_names_explicit(self, tmp_path):
        for i in range(3):
            _make_plan(tmp_path, f"plan-20260817-153{i}-x{i}")
        proc = _run([
            "--work-dir", str(tmp_path),
            "plan-20260817-1530-x0",
            "plan-20260817-1532-x2",
            "--force",
        ])
        assert proc.returncode == 0
        result = _result_from_stdout(proc)
        cleared_names = {c["plan"] for c in result["data"]["cleared"]}
        assert cleared_names == {"plan-20260817-1530-x0", "plan-20260817-1532-x2"}
        assert (tmp_path / ".drive" / "plan-20260817-1531-x1").exists()

    def test_nonexistent_name_silently_skipped(self, tmp_path):
        _make_plan(tmp_path, "plan-20260817-1530-real")
        proc = _run(["--work-dir", str(tmp_path), "plan-not-here", "--force"])
        assert proc.returncode == 0
        result = _result_from_stdout(proc)
        assert result["data"]["cleared"] == []


class TestRunningSkip:
    def test_recent_mtime_skipped(self, tmp_path):
        # 一个老（60 min ago），一个新（5 min ago）
        _make_plan(tmp_path, "plan-20260817-1530-old", mtime_minutes_ago=60)
        _make_plan(tmp_path, "plan-20260817-1531-new", mtime_minutes_ago=5)
        proc = _run(["--work-dir", str(tmp_path), "--all", "--force"])
        assert proc.returncode == 0
        result = _result_from_stdout(proc)
        cleared_names = {c["plan"] for c in result["data"]["cleared"]}
        assert cleared_names == {"plan-20260817-1530-old"}
        assert "plan-20260817-1531-new" in result["data"]["skipped_running"]
        assert (tmp_path / ".drive" / "plan-20260817-1531-new").exists()

    def test_all_running_returns_error(self, tmp_path):
        _make_plan(tmp_path, "plan-20260817-1530-a", mtime_minutes_ago=1)
        _make_plan(tmp_path, "plan-20260817-1531-b", mtime_minutes_ago=2)
        proc = _run(["--work-dir", str(tmp_path), "--all", "--force"])
        assert proc.returncode == 1
        result = _result_from_stdout(proc)
        assert result["reason"] == "all_running"


class TestTarBackup:
    def test_tar_creates_archive(self, tmp_path):
        plan_dir = _make_plan(tmp_path, "plan-20260817-1530-tar", mtime_minutes_ago=60)
        proc = _run(["--work-dir", str(tmp_path), "--tar", "--force"])
        assert proc.returncode == 0
        result = _result_from_stdout(proc)
        tar_path = Path(result["data"]["cleared"][0]["tar_path"])
        assert tar_path.is_file()
        assert tar_path.parent.name == ".cleared"
        # tar 内含原 plan 内容
        with tarfile.open(tar_path, "r:gz") as tf:
            names = tf.getnames()
        assert any("manifest.md" in n for n in names)
        # 原 plan 已被删
        assert not plan_dir.exists()

    def test_cleared_dir_preserved_across_runs(self, tmp_path):
        _make_plan(tmp_path, "plan-20260817-1530-a", mtime_minutes_ago=60)
        _make_plan(tmp_path, "plan-20260817-1531-b", mtime_minutes_ago=120)
        # 第一次清理（备份 + 删）
        _run(["--work-dir", str(tmp_path), "--tar", "--force"])
        cleared_dir = tmp_path / ".drive" / ".cleared"
        assert cleared_dir.is_dir()
        # 第二次清理一个更新的 plan——不应清掉 .cleared/
        _make_plan(tmp_path, "plan-20260817-1532-c", mtime_minutes_ago=180)
        _run(["--work-dir", str(tmp_path), "--keep", "0", "--tar", "--force"])
        assert cleared_dir.is_dir()
        assert len(list(cleared_dir.glob("*.tar.gz"))) >= 1


class TestNoDriveRoot:
    def test_no_drive_root_returns_error(self, tmp_path):
        proc = _run(["--work-dir", str(tmp_path), "--force"])
        assert proc.returncode == 1
        result = _result_from_stdout(proc)
        assert result["reason"] == "no_drive_root"


class TestEdgeCases:
    def test_no_plan_dirs(self, tmp_path):
        (tmp_path / ".drive").mkdir()
        proc = _run(["--work-dir", str(tmp_path), "--all", "--force"])
        assert proc.returncode == 0
        result = _result_from_stdout(proc)
        assert result["data"]["cleared"] == []

    def test_cleared_and_backup_subdirs_not_counted_as_plans(self, tmp_path):
        """已存在的 .cleared/ 和 .planning-backup-* 应被忽略。"""
        (tmp_path / ".drive" / ".cleared").mkdir(parents=True)
        (tmp_path / ".drive" / ".cleared" / "old.tar.gz").write_bytes(b"x")
        (tmp_path / ".drive" / ".planning-backup-20260817-1530.tar.gz").write_bytes(b"x")
        _make_plan(tmp_path, "plan-20260817-1530-real", mtime_minutes_ago=60)
        proc = _run(["--work-dir", str(tmp_path), "--all", "--force"])
        assert proc.returncode == 0
        result = _result_from_stdout(proc)
        assert len(result["data"]["cleared"]) == 1
        assert result["data"]["cleared"][0]["plan"] == "plan-20260817-1530-real"
        # 备份文件仍存在
        assert (tmp_path / ".drive" / ".cleared" / "old.tar.gz").exists()
        assert (tmp_path / ".drive" / ".planning-backup-20260817-1530.tar.gz").exists()