#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tag.py — S2 归类：产出 GWT 归类 + 生成重点解析的提示词。

本脚本只负责"问"：把 GWT 条目与用户要求渲染成 20-tag.prompt.md，
交主 agent 填写 20-tag.answer.json。同时也持有该答案的 schema 校验逻辑
（谁提问谁负责定义答案长什么样）。

配额计算在 plan.py——两者分开，改提示词不会碰到计数逻辑，反之亦然。

无 GWT 时本脚本不产出任何提示词（直接跳过）。

用法：
    python3 tag.py --work <中间态目录> [--input "用户要求"]
"""

import argparse
import sys

import config
from common import (
    GoldevalError,
    fail,
    read_json,
    work_path,
    write_text,
)

TAG_PROMPT_TEMPLATE = """\
# 任务：验收条目归类 + 生成重点解析

你是测试设计专家。请完成两件判断，供配额分配使用。

## 一、把每条验收条目（acceptance_criteria）归类到一个维度

维度定义：

{dimensions}

要求：每条验收条目恰好归入一个维度；依据其 **When/Then 在验证什么**，而不是标题措辞。

## 二、从用户要求中解析"生成重点"

用户要求原文：

```
{user_input}
```

如果其中明确提到要重点覆盖的方向，映射到上述维度 id 列表（可多选，无则给空数组）。
**只做映射，不要发挥**：用户没提的就是空。

## 输出 schema（只输出 JSON，无解释、无 markdown 围栏）

```json
{{
  "gwt_tags": [
    {{"index": 1, "dimension": "functional", "reason": "一句话依据"}}
  ],
  "focus": ["safety", "failure"],
  "focus_reason": "一句话依据"
}}
```

## 验收条目原文

{gwt_block}
"""


# ============================== 提示词渲染 ==============================

def build_tag_prompt(profile, user_input):
    """渲染归类提示词。"""
    dimensions = "\n".join(
        f"- `{d['id']}`（{d['name']}）：{d['desc']}"
        for d in config.DIMENSIONS
    )
    gwts = profile["gwt_baseline"]["entries"]
    block = "\n\n".join(
        f"### #{g['index']} {g['title']}\n"
        f"- Given：{g['given']}\n- When：{g['when']}\n- Then：{g['then']}"
        for g in gwts
    )
    return TAG_PROMPT_TEMPLATE.format(
        dimensions=dimensions,
        user_input=user_input or "（用户未提供额外要求）",
        gwt_block=block,
    )


# ============================== 答案校验 ==============================

def parse_tag_answer(answer, gwts, user_input):
    """校验归类答案；返回 (tags, focus_ids, focus_reason)。

    user_input 参数保留以兼容调用方签名（focus 的合法性只依据维度集合判断）。
    """
    tags = {}
    raw_tags = answer.get("gwt_tags")
    if not isinstance(raw_tags, list):
        raise GoldevalError("归类答案缺少 gwt_tags 数组")

    valid_ids = set(config.DIMENSION_IDS)
    for item in raw_tags:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        dim_id = str(item.get("dimension") or "").strip()
        if dim_id not in valid_ids:
            raise GoldevalError(
                f"GWT #{index} 归类到未知维度 {dim_id!r}；"
                f"合法维度：{sorted(valid_ids)}"
            )
        tags[index] = dim_id

    missing = [g["index"] for g in gwts if g["index"] not in tags]
    if missing:
        raise GoldevalError(f"以下 GWT 未被归类：{missing}")

    focus = answer.get("focus") or []
    if not isinstance(focus, list):
        focus = []
    focus_ids = [str(f).strip() for f in focus if str(f).strip() in valid_ids]

    return tags, focus_ids, str(answer.get("focus_reason") or "").strip()


# ============================== CLI ==============================

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="tag.py", description="S2 归类：产出 GWT 归类与生成重点的提示词"
    )
    parser.add_argument("--work", required=True, help="中间态目录")
    parser.add_argument("--input", dest="user_input", default="")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    profile = read_json(work_path(args.work, "profile"))
    if not profile:
        fail("未找到 12-agent-profile.json，请先运行 freeze_profile.py")

    gwts = profile["gwt_baseline"]["entries"]
    if not gwts:
        print("S2 无验收条目（acceptance_criteria 为空），跳过归类（无需 LLM 出力）")
        return 0

    prompt_path = work_path(args.work, "tag_prompt")
    write_text(prompt_path, build_tag_prompt(profile, args.user_input))

    print(f"S2 待归类：{len(gwts)} 条验收条目需要归类到维度")
    print(f"下一步：读取 {prompt_path}")
    print(f"        并写出 {work_path(args.work, 'tag_answer')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
