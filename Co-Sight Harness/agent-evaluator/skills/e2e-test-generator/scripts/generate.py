#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""generate.py — /goldeval generate 的入口与断点续跑调度。

Claude Code 的斜杠命令不能可靠转发参数，因此 SKILL.md 让主 agent 把
$ARGUMENTS 原样透传到这里，由本脚本负责：
  1. 参数解析与范围校验
  2. 建立中间态目录
  3. 依赖预检，判定当前停在哪一步
  4. 打印"下一步该做什么"的精确指令

后续每次重跑本脚本都会重新预检，因此天然支持断点续跑。

用法：
    python3 generate.py --agent <目录|.zip|.tar.gz> [--count 5] [--input "..."]
                        [--output <run 目录>]
    python3 generate.py --work <run 目录>/generated_datasets/.work
"""

import argparse
import subprocess
import sys
from pathlib import Path

import config
from common import fail, read_json, slug_from_path, stamp_now, work_path, write_json


# ============================== 步骤定义 ==============================

def collect_state(work_dir):
    """盘点中间态目录，返回 {键: 是否存在}。"""
    work_dir = Path(work_dir)
    state = {
        "asset": work_path(work_dir, "asset").is_file(),
        "profile_input": work_path(work_dir, "profile_input").is_file(),
        "merge_answer": work_path(work_dir, "merge_answer").is_file(),
        "profile": work_path(work_dir, "profile").is_file(),
        # 档 B/C（无 GWT）时 tag.py 会跳过、永不产出 20-tag.answer.json，
        # 必须靠画像本身区分"已跳过的无需产出"与"尚未产出"
        "profile_has_gwt": bool(
            ((read_json(work_path(work_dir, "profile")) or {})
             .get("gwt_baseline") or {}).get("entries")
        ),
        "tag_answer": work_path(work_dir, "tag_answer").is_file(),
        "plan": work_path(work_dir, "plan").is_file(),
        "gwt_answers": bool(list(work_dir.glob("30-gwt.answer.json")))
        if work_dir.exists() else False,
        "batch_prompts": sorted(work_dir.glob("30-batch-*.prompt.md"))
        if work_dir.exists() else [],
        "batch_answers": sorted(work_dir.glob("30-batch-*.answer.json"))
        if work_dir.exists() else [],
        "repair_prompts": sorted(work_dir.glob("31-repair-*.prompt.md"))
        if work_dir.exists() else [],
        "repair_answers": sorted(work_dir.glob("31-repair-*.answer.json"))
        if work_dir.exists() else [],
        "verified": work_path(work_dir, "verified").is_file(),
        "verify_report": read_json(work_path(work_dir, "verify_report")),
        "emitted": read_json(work_path(work_dir, "emitted")),
    }
    return state


def _answers_for(prompts):
    """把一个批次的 prompt 列表映射成对应的 answer 路径列表。"""
    return [p.with_name(p.name.replace(".prompt.md", ".answer.json")) for p in prompts]


def _pending(prompts):
    """筛出尚未填写 answer 的**提示词**文件（返回 prompt 而非 answer 路径）。"""
    return [p for p, answer in zip(prompts, _answers_for(prompts))
            if not answer.is_file()]


def _needs_reverify(work_dir, state):
    """补生成答案是否比上次校验更新——是则必须重跑 verify.py。

    verify.py 产出 40-verified.jsonl 后，主 agent 会填一批补生成答案；
    此时 40-verified.jsonl 仍存在，仅凭"verified 是否存在"会漏掉这一轮，
    导致补生成结果被直接丢给 emit.py 而从未被校验吸收。
    """
    report = state["verify_report"]
    if not report or not report.get("gaps"):
        return False
    if report.get("round", 0) >= config.MAX_REPAIR_ROUNDS:
        return False

    verdict_file = work_path(work_dir, "verify_report")
    if not verdict_file.is_file():
        return True

    cutoff = verdict_file.stat().st_mtime
    for answer in _answers_for(state["repair_prompts"]):
        if answer.is_file() and answer.stat().st_mtime > cutoff:
            return True
    return False


def _prompts_ready(work_dir, plan, state):
    """S3 提示词是否已全部产出。

    需要产出的提示词有两类，各自独立判断：
      - GWT 物化提示词：仅当有保留的 GWT 时才需要
      - 批次提示词：仅当配额 > 0 时才需要（数量应与配额的批次数一致）
    """
    work_dir = Path(work_dir)

    if plan.get("gwt_kept") and not work_path(work_dir, "30-gwt.prompt.md").is_file():
        return False

    expected_batches = 0
    for need in (plan.get("quota") or {}).values():
        if need > 0:
            expected_batches += (need + config.BATCH_SIZE - 1) // config.BATCH_SIZE

    return len(state["batch_prompts"]) >= expected_batches


def next_step(work_dir, count, plan, agent_arg, user_input=""):
    """判定当前停在哪一步。

    返回 (步骤标签, 类型, 载荷)：
      类型 "script"      载荷 = 要执行的脚本名与附加参数（可自动执行）
      类型 "llm"         载荷 = 需要主 agent 填写的提示词文件清单
      类型 "done"        载荷 = None
    """
    state = collect_state(work_dir)

    # 注意：带 --agent 的调用在 main() 里就开了一个全新目录，走不到这里；
    # 带 --work 续跑时若真带着已落盘标记进来（例如手工塞的），
    # 落到 "S5 落盘" 也无害——emit.py 自己还有一层幂等守卫。
    if not state["asset"]:
        return "S0 输入解析", "script", [("parse.py", ["--agent", str(agent_arg)])]

    if not state["profile_input"]:
        return "S1 画像抽取", "script", [("extract.py", [])]

    if not state["merge_answer"]:
        return "S1 能力点归并", "llm", [work_path(work_dir, "merge_prompt")]

    if not state["profile"]:
        return "S1 冻结画像", "script", [("freeze_profile.py", [])]

    # S2 拆成两步：tag.py 只出归类提示词，plan.py 只算配额。
    # --input 属于归类提示词的内容（供 LLM 解析生成重点），因此传给 tag.py；
    # plan.py 也收一份，用于写入 plan.json/报告/manifest 供溯源。
    # 无 GWT（档 B/C）时跳过整个归类分支：tag.py 不产出任何提示词，
    # 20-tag.answer.json 也永远不会出现，只认 tag_answer 会导致死循环。
    if state["profile_has_gwt"] and not state["tag_answer"] and not state["plan"]:
        tag_prompt = work_path(work_dir, "tag_prompt")
        if not tag_prompt.is_file():
            return "S2 归类提示词", "script", [
                ("tag.py", ["--input", user_input])
            ]
        return "S2 GWT 归类", "llm", [tag_prompt]

    if not state["plan"]:
        return "S2 计划规划", "script", [
            ("plan.py", ["--count", str(count), "--input", user_input])
        ]

    # S3：先产出全部提示词，再交 LLM 填写。
    # 不能用 batch_prompts 是否存在来判断——当 generated_budget=0 时
    # （GWT 已填满 count）本就不该有批次提示词，否则会反复重跑 prompts.py。
    if not _prompts_ready(work_dir, plan, state):
        return "S3 提示词产出", "script", [("prompts.py", [])]

    if plan.get("gwt_kept") and not state["gwt_answers"]:
        return ("S3 验收基线物化", "llm",
                [work_path(work_dir, "30-gwt.prompt.md")])

    pending_batches = _pending(state["batch_prompts"])
    if pending_batches:
        return "S3 用例生成", "llm", pending_batches

    pending_repairs = _pending(state["repair_prompts"])
    if pending_repairs:
        return "S4 补生成", "llm", pending_repairs

    if not state["verified"] or _needs_reverify(work_dir, state):
        return "S4 校验与去重", "script", [("verify.py", [])]

    # 兜底：verify.py 记录过待填提示词（正常路径由上面的 glob 分支覆盖）
    report = state["verify_report"] or {}
    recorded = [
        Path(work_dir) / name for name in report.get("pending_prompts") or []
        if not (Path(work_dir) /
                name.replace(".prompt.md", ".answer.json")).is_file()
    ]
    if recorded:
        return "S4 补生成", "llm", recorded

    # 把本轮时间戳带下去，好让 task_id 沿用同一份推导（它仍由 <agent 名>_<时间戳>
    # 拼成，与 run 目录名解耦——run 目录可能是用户显式指定的）。
    stamp = (read_json(Path(work_dir) / "run-args.json") or {}).get("stamp")
    emit_args = ["--stamp", stamp] if stamp else []
    return "S5 落盘", "script", [("emit.py", emit_args)]


# ============================== 参数 ==============================

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="generate.py",
        description="goldeval generate：从 Agent 源码目录生成测试用例集",
    )
    parser.add_argument("--agent", help="待评测 agent 目录或压缩包（必填）")
    parser.add_argument("--count", type=int, default=config.COUNT_DEFAULT)
    parser.add_argument("--input", dest="user_input", default="")
    parser.add_argument("--output", dest="output",
                        help="run 目录（默认 outputs/e2e-test-<时间戳>）")
    parser.add_argument("--work", help="中间态目录（<run 目录>/generated_datasets/.work）")
    return parser.parse_args(argv)


def resolve_run_dir(output_arg, stamp):
    """解析本轮 run 目录。

    显式给了 --output 就**原样使用**（mkdir -p 语义，不避让、不改名）；
    否则用默认的 `outputs/e2e-test-<时间戳>`。返回绝对路径，
    以便续跑时无论从哪个 cwd 调用都能定位到同一处。
    """
    if output_arg:
        return Path(output_arg).expanduser().resolve()
    return (config.RUN_PARENT_DIR
            / f"{config.RUN_DIR_PREFIX}-{stamp or stamp_now()}").resolve()


def work_dir_of(run_dir):
    """run 目录下的中间态目录：<run 目录>/generated_datasets/.work。"""
    return Path(run_dir) / config.ARTIFACT_DIRNAME / config.WORK_DIRNAME


def run_dir_of(work_dir):
    """从中间态目录反推 run 目录：<run 目录>/generated_datasets/.work。"""
    return Path(work_dir).resolve().parent.parent


def read_plan(work_dir):
    """读取计划；未生成返回 None（不视为错误）。"""
    payload = read_json(work_path(work_dir, "plan"))
    return payload if isinstance(payload, dict) else None


def guard_run_dir(work_dir, agent_arg, count, user_input):
    """开新一轮前守卫：该 run 目录的中间态已有内容就拒绝。

    判定只看 `.work/` 里有没有文件——S0 本就会把 `generated_datasets/` 与
    `.work/` 建出来，所以「目录存在」不能当信号；而「有文件」必然是某一轮
    留下的，此时既不静默覆盖旧产出，也不假装能接着跑。
    """
    work_dir = Path(work_dir)
    if not work_dir.is_dir():
        return
    if not any(p.is_file() for p in work_dir.iterdir()):
        return

    saved = read_json(work_dir / "run-args.json") or {}
    run_dir = saved.get("out_dir") or run_dir_of(work_dir)
    emitted = read_json(work_path(work_dir, "emitted"))
    if emitted:
        fail(
            f"{run_dir} 已跑完（落盘于 {emitted.get('emitted_at')}，"
            f"{emitted.get('record_count')} 条）\n"
            f"       换一个 --output，或删除该目录后重跑：rm -rf {run_dir}"
        )

    label, _, _ = next_step(work_dir, count, read_plan(work_dir),
                            agent_arg, user_input)
    fail(
        f"{run_dir} 已有未完成的进度（停在 {label}）\n"
        f"       想接着跑：generate.py --work {work_dir}\n"
        f"       想重跑：  rm -rf {run_dir}"
    )


def main(argv=None):
    args = parse_args(argv)

    if not config.COUNT_MIN <= args.count <= config.COUNT_MAX:
        fail(
            f"--count 必须在 {config.COUNT_MIN}~{config.COUNT_MAX} 之间，"
            f"实际 {args.count}"
        )

    # --agent 表示"开新一轮"：解析出 run 目录，从零开始。
    # --work 表示"同一轮续跑"：用给定中间态目录，保留已填答案接着往下走。
    # 产出位置一律从 run-args.json 的 out_dir 读，因此续跑时 --work 指到哪
    # 都不影响交付物落在哪——始终是首跑那一份 run 目录。
    if args.work:
        work_dir = Path(args.work).expanduser().resolve()
        saved = read_json(work_dir / "run-args.json") or {}
        recorded = saved.get("out_dir")
        if not recorded:
            fail(
                f"该中间态没有记录产出位置（run-args.json 里无 out_dir）：{work_dir}\n"
                "       它可能是改造前的旧中间态，或手工建的目录\n"
                "       开新一轮：generate.py --agent <被测 agent>"
            )
        # 两个旗同时给出时校验一致：指向同一个 run 目录算重复声明，放行；
        # 矛盾则一定是误解，当场说清楚而不是静默二选一。
        if args.output:
            claimed = Path(args.output).expanduser().resolve()
            if claimed != Path(recorded).resolve():
                fail(
                    "--output 与 --work 指向不同 run 目录\n"
                    f"       --output：{claimed}\n"
                    f"       --work  记录的：{recorded}"
                )
        out_dir = Path(recorded)
        work_dir.mkdir(parents=True, exist_ok=True)
    else:
        if not args.agent:
            fail("请提供 --agent（开新一轮），或带 --work 续跑")
        stamp = stamp_now()
        out_dir = resolve_run_dir(args.output, stamp)
        work_dir = work_dir_of(out_dir)
        guard_run_dir(work_dir, args.agent, args.count, args.user_input)
        work_dir.mkdir(parents=True, exist_ok=True)
        write_json(work_dir / "run-args.json", {
            "agent": args.agent,
            "count": args.count,
            "input": args.user_input,
            "stamp": stamp,
            "out_dir": str(out_dir),
        })

    saved = read_json(work_dir / "run-args.json") or {}
    if not args.agent:
        args.agent = saved.get("agent")
    if not args.agent:
        fail("中间态目录里没有记录 --agent，请显式提供")
    # 续跑时若未显式给出，沿用首次运行记录的参数
    if not args.user_input:
        args.user_input = saved.get("input", "")
    if args.count == config.COUNT_DEFAULT and saved.get("count"):
        args.count = saved["count"]

    scripts_dir = Path(__file__).resolve().parent
    print(f"run 目录：{out_dir}")
    print(f"中间态目录：{work_dir}")

    # 自动推进全部确定性步骤，直到需要 LLM 出力（或落盘完成）。
    # 这样主 agent 只需在真正的 LLM 节点介入，无需在脚本之间来回搬运。
    for _ in range(12):
        plan = read_plan(work_dir)
        label, kind, payload = next_step(
            work_dir, args.count, plan, args.agent, args.user_input
        )

        if kind == "llm":
            print(f"\n当前步骤：{label}（需要你出力）")
            print()
            for prompt in payload:
                print(f"  读取：{prompt}")
            print()
            print("  按提示词内的 schema 生成结果，写出同名 .answer.json")
            print("  （多个批次可交 Task 子 agent 并行）")
            print("\n  写完后重跑本命令续跑：")
            print(f"    python3 {scripts_dir / 'generate.py'} "
                  f"--work {work_dir} --count {args.count}")
            return 0


        # script 类型：顺序执行，任一失败立即透传其退出码
        for script_name, extra in payload:
            command = [sys.executable, str(scripts_dir / script_name),
                       "--work", str(work_dir)] + extra
            print(f"\n▶ {label}：{script_name}")
            result = subprocess.run(command)
            if result.returncode != 0:
                return result.returncode

        # emit.py 是终点（中间态保留，由 50-emitted.json 标记完成）
        if script_name == "emit.py":
            return 0

    fail("步骤推进超过上限，可能存在状态未收敛（请检查 .work/）")


if __name__ == "__main__":
    sys.exit(main())
