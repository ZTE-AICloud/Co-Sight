# -*- coding: utf-8 -*-
"""通用状态机骨架(模板)— 适用于任意包含 LLM 断点的 Skill

子 Agent 用此模板作为骨架生成实际的 scripts/run.py。
具体业务步骤由 spec §4 推断,本骨架只提供:
  1. 状态字段命名约定(checkpoint + phase_history)
  2. 持久化函数(save_state / load_state)
  3. LLM 断点退出协议
  4. Revision loop 自动回退机制
  5. --resume 协议

不绑定任何特定业务参数。subagent 复制后,只替换"具体步骤调度逻辑"。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# === 退出码(参考 state_machine_norms.md) ===
EXIT_OK = 0
EXIT_LLM_CHECKPOINT = 10   # LLM 断点退出(非错误,需 CC 推理后 --resume)
EXIT_VALIDATION_FAIL = 1  # 校验失败(可恢复,自动回退到 pending)


# === 状态文件路径(由调用方注入,不假设具体路径) ===
def state_path_for(middle_dir: Path) -> Path:
    """状态文件路径:由 run.py 决定,统一存到 middle_dir/run_state.json"""
    return middle_dir / "run_state.json"


def save_state(middle_dir: Path, checkpoint: str, history: list) -> Path:
    """持久化当前 checkpoint(通用)。"""
    path = state_path_for(middle_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "checkpoint": checkpoint,
        "last_updated": _now_iso(),
        "phase_history": history,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_state(middle_dir: Path) -> dict:
    """读取当前状态。"""
    path = state_path_for(middle_dir)
    if not path.exists():
        raise FileNotFoundError(f"状态文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


# === LLM 断点协议(通用) ===
def need_llm_checkpoint(middle_dir: Path, task_id: str, task_type: str,
                        prompt_path: Path, response_schema: dict,
                        context: dict, state: dict) -> None:
    """写入 LLM 任务文件 + 状态推进到 pending + 退出码 0(非错误)。

    subagent 复制此函数,只替换 state 推进逻辑。
    """
    task_file = middle_dir / f"llm_task_{task_id}.json"
    task_payload = {
        "task_id": task_id,
        "task_type": task_type,
        "prompt_template": str(prompt_path),
        "response_schema": response_schema,
        "context": context,
        "response_expected": str(middle_dir / f"llm_response_{task_id}.json"),
    }
    task_file.write_text(json.dumps(task_payload, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    # 状态推进:done → pending(等 CC 推理)
    state["checkpoint"] = f"step{task_id}_pending"
    state["phase_history"].append({
        "phase": state["checkpoint"],
        "status": "pending",
        "timestamp": _now_iso(),
        "retry_count": 0,
    })
    save_state(middle_dir, state["checkpoint"], state["phase_history"])

    print(f"[LLM-{task_id}] {task_type}")
    print(f"  任务文件: {task_file}")
    print(f"  请推理后将响应写入: {task_payload['response_expected']}")
    print("  然后用 --resume --llm-response <path> 继续")
    sys.exit(EXIT_OK)  # 非错误退出


def handle_llm_resume(middle_dir: Path, task_id: str, state: dict) -> dict:
    """CC 推理后,从 llm_response_X.json 读响应 + 推进状态。

    subagent 复制此函数,只替换"应用 LLM 响应"的具体逻辑。
    """
    response_file = middle_dir / f"llm_response_{task_id}.json"
    if not response_file.exists():
        raise FileNotFoundError(f"LLM 响应文件不存在: {response_file}")

    response = json.loads(response_file.read_text(encoding="utf-8"))

    # 状态推进:pending → llm_done
    state["checkpoint"] = f"step{task_id}_llm_done"
    state["phase_history"].append({
        "phase": state["checkpoint"],
        "status": "llm_done",
        "timestamp": _now_iso(),
        "retry_count": 0,
    })
    save_state(middle_dir, state["checkpoint"], state["phase_history"])

    return response


# === Revision loop:校验失败自动回退(通用) ===
def validate_or_revert(middle_dir: Path, validator_script: Path,
                       validate_args: list, state: dict,
                       revert_checkpoint: str) -> bool:
    """通用 revision loop:运行校验脚本,失败则回退到 revert_checkpoint。

    Args:
        validator_script: 校验脚本绝对路径(validate_topology / validate_content / validate_output)
        validate_args: 传给校验脚本的参数
        state: 当前状态字典
        revert_checkpoint: 失败时回退到哪个 checkpoint(如 "step7_pending")

    Returns:
        True = 校验通过,False = 校验失败(已自动回退 + 退出码 1)
    """
    import subprocess
    result = subprocess.run(
        ["python3", str(validator_script)] + validate_args,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True

    # 校验失败 → 写错误报告 + 回退到 pending
    report_path = middle_dir / "validation_errors.json"
    report_path.write_text(json.dumps({
        "validator": validator_script.name,
        "stderr": result.stderr,
        "stdout": result.stdout,
        "hint": f"请修正后 --resume(回退到 {revert_checkpoint})",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    state["checkpoint"] = revert_checkpoint
    state["phase_history"].append({
        "phase": revert_checkpoint,
        "status": "reverted",
        "timestamp": _now_iso(),
        "retry_count": state["phase_history"][-1].get("retry_count", 0) + 1,
    })
    save_state(middle_dir, state["checkpoint"], state["phase_history"])

    print(f"[VALIDATION-FAIL] {validator_script.name}")
    print(f"  错误报告: {report_path}")
    print(f"  已回退到 checkpoint={revert_checkpoint}")
    print("  请修正后 --resume --llm-response <path>")
    sys.exit(EXIT_VALIDATION_FAIL)


# === CLI 入口(骨架) ===
def main():
    parser = argparse.ArgumentParser(description="Skill 主控(状态机骨架)")
    parser.add_argument("--workspace", required=True, help="需求工作目录")
    parser.add_argument("--middle-dir", required=True,
                        help="中间产物目录(由 run.py 决定)")
    parser.add_argument("--resume", action="store_true",
                        help="从 LLM 断点恢复")
    parser.add_argument("--llm-response", default="",
                        help="LLM 响应文件路径")
    # 其他业务参数由 spec §1.1 推断,subagent 添加
    args = parser.parse_args()

    middle_dir = Path(args.middle_dir)

    # 启动模式:初始化 state
    if not args.resume:
        save_state(middle_dir, "init", [{
            "phase": "init", "status": "done",
            "timestamp": _now_iso(), "retry_count": 0,
        }])
        # subagent 在此处添加具体的步骤调度逻辑
        # 遇到 LLM 断点 → need_llm_checkpoint()
        # 遇到校验 → validate_or_revert()

    # 恢复模式:从 state 读 checkpoint,决定从哪步恢复
    else:
        state = load_state(middle_dir)
        checkpoint = state["checkpoint"]
        # subagent 在此处添加:从 checkpoint 恢复,调 handle_llm_resume()


if __name__ == "__main__":
    main()