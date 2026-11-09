"""review 子流程的触发判定与 summary 去重。

两条不变量：
  - select 的判定必须确定 —— 派 reviewer 时与 wave barrier 自检时调的是同一函数，
    两处结论不一致会让"跳过 review 的 task"被误判成"漏了 REVIEW.md"。
  - merge 必须把同 task_id 合成一条 —— aggregate.py 对重复 task_id 直接判 fail，
    重派场景下不合流就会卡住整个 wave。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = PLUGIN_ROOT / "skills" / "drive" / "scripts" / "review_flow.py"

sys.path.insert(0, str(SCRIPT.parent))
import review_flow as rf  # noqa: E402

pytestmark = pytest.mark.unit


def code_summary(task_id: str, **overrides):
    """一条默认会被选中 review 的 code-mode summary。"""
    base = {
        "task_id": task_id,
        "status": "completed",
        "mode": "code",
        "task_category": "single_file",
        "files_changed": ["src/app.py"],
    }
    base.update(overrides)
    return base


# ---- select：触发条件 ----


def test_code_mode_with_source_file_is_selected():
    out = rf.select([code_summary("T01")])
    assert out["selected"] == ["T01"]
    assert out["skipped"] == []


def test_analysis_mode_is_skipped():
    out = rf.select([code_summary("T01", mode="analysis")])
    assert out["selected"] == []
    assert out["skipped"][0]["task_id"] == "T01"
    assert "mode" in out["skipped"][0]["reason"]


def test_doc_only_change_is_skipped():
    out = rf.select([code_summary("T01", files_changed=["README.md", "docs/a.md"])])
    assert out["selected"] == []
    assert "无代码文件" in out["skipped"][0]["reason"]


def test_mixed_doc_and_code_is_selected():
    """只要有一个代码文件就该审。"""
    out = rf.select([code_summary("T01", files_changed=["README.md", "src/a.py"])])
    assert out["selected"] == ["T01"]


def test_simple_category_is_skipped():
    out = rf.select([code_summary("T01", task_category="simple")])
    assert out["selected"] == []
    assert "task_category" in out["skipped"][0]["reason"]


def test_unfinished_status_is_skipped():
    """failed / partial 的产出还要重做，审它是浪费。"""
    for status in ("failed", "partial", "skipped"):
        out = rf.select([code_summary("T01", status=status)])
        assert out["selected"] == [], f"status={status} 不该被选中"


def test_empty_files_changed_is_skipped():
    out = rf.select([code_summary("T01", files_changed=[])])
    assert out["selected"] == []


def test_config_suffixes_count_as_docs():
    """yaml / json / toml 属配置，无注入面。"""
    out = rf.select([code_summary("T01", files_changed=["a.yaml", "b.json", "c.toml"])])
    assert out["selected"] == []


def test_suffix_match_is_case_insensitive():
    out = rf.select([code_summary("T01", files_changed=["README.MD", "NOTES.TXT"])])
    assert out["selected"] == []


def test_missing_task_id_counts_as_invalid():
    out = rf.select([{"status": "completed", "mode": "code"}, code_summary("T02")])
    assert out["selected"] == ["T02"]
    assert out["invalid_count"] == 1


def test_non_dict_entry_counts_as_invalid():
    out = rf.select(["not-a-dict", code_summary("T01")])
    assert out["selected"] == ["T01"]
    assert out["invalid_count"] == 1


def test_execution_mode_alias_is_honored():
    """summary 可能用 execution_mode 而非 mode 字段名。"""
    out = rf.select([
        {
            "task_id": "T01",
            "status": "completed",
            "execution_mode": "analysis",
            "files_changed": ["src/a.py"],
        }
    ])
    assert out["selected"] == []


def test_absent_mode_falls_back_to_reviewable():
    """mode 缺失时按可审处理 —— 宁可多审一次，不要漏审代码。"""
    out = rf.select([
        {"task_id": "T01", "status": "completed", "files_changed": ["src/a.py"]}
    ])
    assert out["selected"] == ["T01"]


def test_selected_count_matches_list():
    out = rf.select([code_summary("T01"), code_summary("T02"), code_summary("T03")])
    assert out["selected_count"] == len(out["selected"]) == 3


# ---- merge：去重 ----


def test_same_task_id_keeps_last():
    first = code_summary("T01", files_changed=["src/old.py"])
    second = code_summary("T01", files_changed=["src/new.py"])
    out = rf.merge([first, second])
    assert out["count"] == 1
    assert out["summaries"][0]["files_changed"] == ["src/new.py"]
    assert out["replaced"] == ["T01"]


def test_distinct_task_ids_all_kept():
    out = rf.merge([code_summary("T01"), code_summary("T02")])
    assert out["count"] == 2
    assert {s["task_id"] for s in out["summaries"]} == {"T01", "T02"}
    assert out["replaced"] == []


def test_three_versions_keeps_newest():
    out = rf.merge([
        code_summary("T01", files_changed=["v1.py"]),
        code_summary("T01", files_changed=["v2.py"]),
        code_summary("T01", files_changed=["v3.py"]),
    ])
    assert out["count"] == 1
    assert out["summaries"][0]["files_changed"] == ["v3.py"]


def test_merge_output_has_no_duplicate_task_ids():
    """喂给 aggregate.py 的数组必须无重复 —— 这是本函数存在的理由。"""
    out = rf.merge([
        code_summary("T01"), code_summary("T02"),
        code_summary("T01"), code_summary("T03"), code_summary("T02"),
    ])
    ids = [s["task_id"] for s in out["summaries"]]
    assert len(ids) == len(set(ids)) == 3


def test_merge_empty_array():
    out = rf.merge([])
    assert out["count"] == 0
    assert out["summaries"] == []


def test_merge_drops_entries_without_task_id():
    out = rf.merge([{"status": "completed"}, code_summary("T01")])
    assert out["count"] == 1
    assert out["invalid_count"] == 1


# ---- CLI ----


def run_cli(*args, stdin_text=None):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, input=stdin_text,
    )
    return proc


def test_cli_select_via_stdin():
    payload = json.dumps([code_summary("T01"), code_summary("T02", mode="analysis")])
    proc = run_cli("select", "--stdin", stdin_text=payload)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["ok"] is True
    assert out["data"]["selected"] == ["T01"]


def test_cli_merge_via_stdin():
    payload = json.dumps([
        code_summary("T01", files_changed=["src/old.py"]),
        code_summary("T01", files_changed=["src/new.py"]),
    ])
    proc = run_cli("merge", "--stdin", stdin_text=payload)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["data"]["count"] == 1
    assert out["data"]["summaries"][0]["files_changed"] == ["src/new.py"]


def test_cli_rejects_non_array():
    proc = run_cli("select", "--summaries", '{"task_id": "T01"}')
    assert proc.returncode == 1
    out = json.loads(proc.stdout)
    assert out["ok"] is False
    assert out["reason"] == rf.REASON_SCHEMA_INVALID


def test_cli_rejects_malformed_json():
    proc = run_cli("select", "--summaries", "{not json")
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["reason"] == rf.REASON_SCHEMA_INVALID


def test_cli_requires_an_input_source():
    proc = run_cli("select")
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["reason"] == rf.REASON_INVALID_ARG


def test_cli_missing_file_reports_file_missing():
    proc = run_cli("select", "--summaries-file", "/nonexistent/s.json")
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["reason"] == rf.REASON_FILE_MISSING


def test_cli_requires_subcommand():
    proc = run_cli()
    assert proc.returncode != 0
