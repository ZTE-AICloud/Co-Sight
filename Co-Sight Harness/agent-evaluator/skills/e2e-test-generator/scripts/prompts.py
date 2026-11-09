#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prompts.py — S3 用例生成的提示词产出。

按计划把每个 (维度, 批次) 展开成一个提示词文件，交主 agent（或 Task 子 agent）填写：
  <work>/30-gwt.prompt.md                 档 A：全部保留的 GWT 一次性物化
  <work>/30-batch-<dimension>-<n>.prompt.md   缺口用例生成

用法：
    python3 prompts.py --work <中间态目录>
"""

import argparse
import json
import sys

import config
from common import (
    fail,
    read_json,
    work_path,
    write_text,
)

HARD_CONSTRAINTS = """\
## 硬性约束（违反即为无效产出）

1. `input` 必须**自包含、可独立复现**，不得引用「上文」「前面提到的」等语境依赖表述。
2. `expected_output` 必须是**可判定要点**（逐条列出），不写「合理即可」「处理得当」类模糊表述。
3. 不得与下方「禁止重复素材」中的内容**重复或近义改写**。
4. {capability_rule}
5. 只输出 JSON，无解释、无 markdown 围栏。
"""

PROFILE_BRIEF = """\
## 被测 Agent 画像

- 根目录：`{root}`
- 档位：`{tier}`{tier_reason}
- 定位：{positioning}
- 能力边界：{boundary}
- 可用工具：{tools}
- 关键约束：{constraints}
- CLI 形态：{cli}
- 退出码契约：{exit_codes}

### 能力点清单

{capabilities}
"""

# 注意：本模板含字面 JSON 花括号，不能用 str.format，改用 <<TOKEN>> 替换。
CASE_SCHEMA_TEMPLATE = """\
## 输出 schema（只输出 JSON）

```json
{
  "cases": [
    {
      "input": "评测时原样发给被测 Agent 的输入",
      "precondition": "这条用例成立所需的前置条件（纯文本描述，不落盘任何文件）",
      "expected_output": ["可判定要点 1", "可判定要点 2"],
<<GWT_FIELD>><<CAPABILITY_FIELD>>
      "reasoning": "为什么这条用例能验证该能力点（一句话）"
    }
  ]
}
```
"""

GWT_INDEX_FIELD = '      "gwt_index": 1,\n'


def render_case_schema(profile, with_gwt_index=False):
    """渲染用例 schema 片段（能力点字段、GWT 归属字段的有无）。"""
    if profile.get("capabilities"):
        field = '      "capability_ref": "C01",'
    else:
        field = "      // 本档无能力点：不要输出 capability_ref 字段"
    return (
        CASE_SCHEMA_TEMPLATE
        .replace("<<GWT_FIELD>>", GWT_INDEX_FIELD if with_gwt_index else "")
        .replace("<<CAPABILITY_FIELD>>", field)
    )


# ============================== 画像摘要 ==============================

def summarize_profile(profile):
    """把画像压成提示词用的短摘要。"""
    boundaries = profile.get("boundaries") or {}
    engine = profile.get("engine") or {}
    capabilities = profile.get("capabilities") or []

    positioning = (boundaries.get("positioning") or "").strip().splitlines()
    positioning = positioning[0] if positioning else "（未声明）"

    boundary_text = (boundaries.get("capability_boundary") or "").strip()
    boundary_text = " / ".join(boundary_text.splitlines()[:4]) or "（未声明）"

    tools = (profile.get("tools") or {}).get("allow") or []
    constraints = profile.get("constraints") or {}

    cap_lines = "\n".join(
        f"- `{c['id']}` {c['name']}：{c['desc']}" for c in capabilities
    ) or "（无——档 C 降级，自由生成）"

    return {
        "root": profile["root"],
        "tier": profile["tier"],
        "tier_reason": f"（{profile['tier_reason']}）" if profile.get("tier_reason") else "",
        "positioning": positioning,
        "boundary": boundary_text,
        "tools": "、".join(tools) or "（未声明）",
        "constraints": json.dumps(constraints, ensure_ascii=False) if constraints else "（未声明）",
        "cli": "、".join(engine.get("cli_args") or []) or "（未识别）",
        "exit_codes": json.dumps(engine.get("exit_codes") or [], ensure_ascii=False),
        "capabilities": cap_lines,
    }


def render_profile_brief(profile):
    return PROFILE_BRIEF.format(**summarize_profile(profile))


def capability_rule(profile):
    caps = profile.get("capabilities") or []
    if not caps:
        return "本档无能力点（档 C 降级）：**不要输出 `capability_ref` 字段**。"
    ids = "、".join(f"`{c['id']}`" for c in caps)
    return f"`capability_ref` 必须是以下能力点 id 之一：{ids}"




# ============================== 禁止重复素材 ==============================

def exclusion_block(profile, existing_inputs):
    """构造「禁止重复素材」段落。"""
    chunks = []

    gwts = (profile.get("gwt_baseline") or {}).get("entries") or []
    if gwts:
        lines = [f"- #{g['index']}：{g['given']}" for g in gwts if g.get("given")]
        if lines:
            chunks.append("### 验收基线（acceptance_criteria）的 Given（全部豁免，不得换皮重出）\n" + "\n".join(lines))

    demo = profile.get("demo_code") or {}
    for item in (demo.get("files") or [])[:5]:
        head = (item.get("head") or "").strip()
        if head:
            chunks.append(f"### 自带演示文件 `{item['file']}`（不得直接当测试输入）\n```\n{head}\n```")

    if existing_inputs:
        lines = [f"- {text}" for text in existing_inputs[:30]]
        chunks.append("### 本批次之前已生成的 input（不得重复或近义改写）\n" + "\n".join(lines))

    return "\n\n".join(chunks) or "（无可比对的素材）"


# ============================== 提示词模板 ==============================

GWT_PROMPT_HEADER = """\
# 任务：验收基线物化（档 A）

下面是被测 Agent 的验收契约（`clarified-agent-requirements.yaml`）中
`acceptance_criteria` 的验收条目。
请把它们**逐条物化**成可评测的测试用例。

要点：
- `input` 写成评测时原样发给被测 Agent 的话，保持其真实入参形态。
- `precondition` 用自然语言说明该用例成立所需的前置条件（不落盘文件）。
- `expected_output` 把 GWT 的 **Then** 拆成逐条可判定的要点；Then 里无法判定的表述
  （如「给出修复建议」）要么拆细到可判定，要么省略。
- `gwt_index` 填这条用例来源的验收条目编号（见下方条目标题里的 `#编号`，
  对应 `acceptance_criteria` 列表中的位置）。
  一条验收条目通常生成一条用例；若它覆盖多种输入（如 Then 里列了多种错误类型），
  可以拆成多条用例，但每条都必须填同一个 `gwt_index`。

"""

BATCH_PROMPT_HEADER = """\
# 任务：生成测试用例

请为维度 **`{dim_id}`（{dim_name}）** 生成 **{need}** 条测试用例。

维度说明：{dim_desc}

"""


def build_gwt_prompt(profile, plan, work_dir):
    kept = plan["gwt_kept"]
    if not kept:
        return None

    block = "\n\n".join(
        f"### #{g['index']} {g['title']}\n"
        f"- **Given**：{g['given']}\n"
        f"- **When**：{g['when']}\n"
        f"- **Then**：{g['then']}"
        for g in kept
    )
    body = [
        GWT_PROMPT_HEADER,
        render_profile_brief(profile),
        HARD_CONSTRAINTS.format(capability_rule=capability_rule(profile)),
        render_case_schema(profile, with_gwt_index=True),
        "## 待物化的验收条目\n\n" + block,
    ]
    path = work_path(work_dir, "30-gwt.prompt.md")
    write_text(path, "\n".join(body))
    return path


def build_batch_prompts(profile, plan, work_dir):
    """按 (维度, 批次) 展开提示词文件。"""
    written = []
    quota = plan["quota"]

    for dim_id in config.DIMENSION_IDS:
        need = quota.get(dim_id, 0)
        if need <= 0:
            continue
        dim = config.dimension_by_id(dim_id)

        for batch_index, start in enumerate(range(0, need, config.BATCH_SIZE), 1):
            size = min(config.BATCH_SIZE, need - start)
            header = BATCH_PROMPT_HEADER.format(
                dim_id=dim_id,
                dim_name=dim["name"],
                need=size,
                dim_desc=dim["desc"],
            )
            body = [
                header,
                render_profile_brief(profile),
                HARD_CONSTRAINTS.format(capability_rule=capability_rule(profile)),
                render_case_schema(profile),
                "## 禁止重复素材\n\n" + exclusion_block(profile, []),
            ]
            path = work_path(work_dir, f"30-batch-{dim_id}-{batch_index}.prompt.md")
            write_text(path, "\n".join(body))
            written.append(path)

    return written


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="prompts.py", description="S3 提示词产出：GWT 物化 + 各批次生成"
    )
    parser.add_argument("--work", required=True, help="中间态目录")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    profile = read_json(work_path(args.work, "profile"))
    plan = read_json(work_path(args.work, "plan"))
    if not profile or not plan:
        fail("未找到画像或计划，请先运行 freeze_profile.py 与 plan.py")

    gwt_prompt = build_gwt_prompt(profile, plan, args.work)
    batch_prompts = build_batch_prompts(profile, plan, args.work)

    if gwt_prompt:
        print(f"GWT 物化提示词：{gwt_prompt}")
    print(f"批次提示词 {len(batch_prompts)} 个：")
    for path in batch_prompts:
        print(f"    {path.name}")

    print("\n下一步：为每个提示词写出同名 answer 文件（.prompt.md → .answer.json）")
    print("        可自行用 Task 子 agent 并行处理多个批次。")
    print(f"        然后运行：python3 verify.py --work {args.work}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
