#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""conftest.py — 把 scripts/ 挂到 sys.path，并提供公共 fixture。

全部测试都是纯确定性的：不调 claude CLI、不发网络请求。裁判由主 agent 派的 Task
承担，脚本里没有任何 LLM 节点，所以这里连 subprocess 都不用打桩。
"""

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import config  # noqa: E402  （必须先挂 sys.path）

RUN_PARENT_DIR = config.RUN_PARENT_DIR


def seed_record(data_id="agent_functional_001", **overrides):
    """构造一条 seed 记录（形状对齐 e2e-test-runner 的落盘格式）。"""
    record = {
        "data_id": data_id,
        "kind": "seed",
        "dimension": "functional",
        "source": "gwt",
        "source_ref": "pass-criteria.md#1",
        "input": "请对 ./demo_code 目录做明文密码检查",
        "precondition": "被测 Agent 工程根下存在 ./demo_code 目录",
        "expected_output": ["报告命中该 Java 源文件", "严重度标记为 P1"],
        "capability_ref": "C01",
        "run": {
            "status": "passed",
            "exit_code": 0,
            "elapsed_seconds": 41.5,
            "timed_out": False,
            "result_preview": "预检失败，流程终止。",
            "case_dir": "",
            "workspace_dir": "",
        },
    }
    record.update(overrides)
    return record


def answer_payload(data_id, expected, *, run_valid=True, verdicts=None,
                   scores=None, invalid_reason=None):
    """构造一份合法裁判答案。

    刻意**不**直接拼字段，而是从 render._answer_schema 生成的真实模板出发填值——
    这样模板缺字段时这里也缺，校验器会当场报错。夹具一旦比真实协议"更慷慨"，
    协议少了字段就永远发现不了（data_id 曾经就这样漏过一整轮）。
    """
    import json

    import render

    verdicts = verdicts or ["hit"] * len(expected)
    scores = scores or {"correctness": 5, "completeness": 5,
                        "format_compliance": 5, "actionability": 5}
    payload = json.loads(render._answer_schema(expected, data_id))
    payload["run_valid"] = run_valid
    payload["invalid_reason"] = invalid_reason if invalid_reason is not None else (
        None if run_valid else "目标路径不存在")
    payload["items"] = [{"text": text, "verdict": verdict, "note": "n"}
                        for text, verdict in zip(expected, verdicts)]
    payload["reasoning"] = "因为所以"
    payload.update(scores)
    return payload


@pytest.fixture
def make_run(tmp_path):
    """建一个 runner 形态的 run 目录：<run>/run_datasets/{seed.jsonl, {id}/...}。

    返回 (run_dir, seed_path, records)，并把每条记录的 case_dir / workspace_dir
    指向真实建出来的用例目录——证据装载和守卫都依赖这两个字段。
    """
    def _make(records, *, run_name="e2e-test-20260101-000000",
              with_manifest=False, manifest=None, make_workspaces=True):
        # run 目录落在 outputs/ 之下，与 --input/--output 的默认探测根一致
        run_dir = tmp_path / RUN_PARENT_DIR / run_name
        artifact = run_dir / "run_datasets"
        artifact.mkdir(parents=True)

        for record in records:
            case_dir = artifact / str(record["data_id"])
            case_dir.mkdir(parents=True, exist_ok=True)
            workspace = case_dir / "workspace"
            if make_workspaces:
                workspace.mkdir(exist_ok=True)
            # 直接赋值而非 setdefault：seed_record 的 run 里已带空串占位，
            # setdefault 会留住那个空值，证据装载与守卫就都失效了。
            run = record.setdefault("run", {})
            run["case_dir"] = str(case_dir)
            run["workspace_dir"] = str(workspace)

        seed_path = artifact / "seed.jsonl"
        seed_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
            encoding="utf-8")

        if with_manifest or manifest is not None:
            payload = manifest or {"agent_root": str(tmp_path / "agent_root")}
            (artifact / "run-manifest.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return run_dir, seed_path, records
    return _make


@pytest.fixture
def write_result_json():
    """往某条用例的 case_dir 里落一份 result.json。"""
    def _write(record, payload):
        from pathlib import Path as _Path
        case_dir = _Path(record["run"]["case_dir"])
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "result.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return _write
