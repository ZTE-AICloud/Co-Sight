#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render.py — 把一条用例 + 其证据渲染成裁判 prompt。

刻意不做的事：不生成多个文件、不引用外部模板、不做条件分支的格式变体。
一条用例一份纯文本，内容全部内联——裁判会话因此**不碰文件系统**（只写自己那份
answer.json），路径解析这个易错环节被收敛到脚本一处（Q7/Q21）。
"""

import json
from pathlib import Path

import config
import common

# skill 根目录：<skill>/scripts/render.py → <skill>
SKILL_ROOT = Path(__file__).resolve().parent.parent
RUBRIC_PATH = SKILL_ROOT.joinpath(*config.RUBRIC_RELPATH)

# 落盘路径在渲染时才知道，先占位、渲染后替换。
ANSWER_PATH_PLACEHOLDER = "{{ANSWER_PATH}}"


def load_rubric() -> str:
    """读取随 skill 分发的评分细则副本。

    固定读 skill 内那份（不读仓库根的同名文件）——自包含，cwd 切到哪都不受影响。
    """
    try:
        text = RUBRIC_PATH.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise common.EvalError(f"读不到评分细则：{RUBRIC_PATH}（{exc}）") from exc
    if not text:
        raise common.EvalError(f"评分细则为空：{RUBRIC_PATH}")
    return text


def _bullets(items: list, start: int = 1) -> str:
    return "\n".join(f"{i}. {text}" for i, text in enumerate(items, start))


def _meta_block(meta: dict) -> str:
    """执行元数据。值是 None 的键不渲染——空字段比缺席更误导。"""
    lines = [f"- {key}: {value}" for key, value in meta.items() if value is not None]
    return "\n".join(lines) if lines else "（无）"


# 校验器除了四维分与 items 之外要求的所有字段，逐个列在模板里。
# 模板**必须与 validate.validate_answer 的要求严格对齐**——曾经漏过 data_id，
# 裁判照着模板写就必然不合格，白白浪费一整轮裁判调用。
# tests/test_prompt.py::test_schema_covers_every_required_key 守这条。
def _answer_schema(expected: list, data_id: str) -> str:
    """给裁判的输出模板。items 用真实条目数占位，逼它逐项对齐。"""
    items = [
        {"text": text, "verdict": "hit | miss | unverifiable", "note": "判定依据（一句话）"}
        for text in expected
    ]
    payload = {
        config.DATA_ID_KEY: data_id,
        config.ANS_RUN_VALID: True,
        config.ANS_INVALID_REASON: "run_valid 为 false 时必填；否则 null",
        config.ANS_ITEMS: items,
        **{dim: "1~5 的整数" for dim in config.DIMENSIONS},
        config.ANS_REASONING: "四维打分的整体理由（3~5 句）",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_prompt(record: dict, expected: list, evidence: str, evidence_source: str,
                 workspace_dir: str) -> str:
    """渲染一条用例的裁判 prompt（含细则全文与全部证据）。"""
    data_id = str(record.get(config.DATA_ID_KEY))
    dimension = record.get(config.DIMENSION_KEY)
    kind = record.get(config.KIND_KEY)
    precondition = str(record.get(config.PRECONDITION_KEY) or "（未声明）")
    meta = common.execution_meta_of(record)

    verdict_rules = "\n".join([
        f"- `{config.VERDICT_HIT}`：期望项在证据中被**明确兑现**。",
        f"- `{config.VERDICT_MISS}`：证据表明该项**未兑现**（做错了、或压根没做）。",
        f"- `{config.VERDICT_UNVERIFIABLE}`：证据不足以判断（如输出被截断、"
        f"关键产物未生成且无从推断）。**单列，不算命中也不算未命中。**",
    ])

    return f"""# 评测任务：对一条 Agent 用例的执行结果打分

你是评测裁判。请**严格按下方评分细则**，对一条已执行完的用例打分。
只输出一份 JSON，不要任何额外文字、不要 Markdown 代码围栏。

---

## 一、评分细则（唯一依据，全文如下）

{load_rubric()}

---

## 二、本数据形态下的落地解释

评分细则来自上游协议，有两处判据在当前测试集里没有对应字段。**按以下解释执行**，
不要因为找不到字段而拒判：

1. **`expected_output` 没有 required / optional 标注**。因此把 `expected_output`
   **整体视为 required**：逐项判定后算命中率，命中率直接映射 completeness 档位
   （5/5→5，4/5→4，3/5→3，依此类推；命中率 <30% 即 5 项中命中 ≤1 项→1）。
   `{config.VERDICT_UNVERIFIABLE}` 的项**不计入分子也不计入分母**；
   若全部项都无法判定，completeness 记 1 并在 reasoning 里说明。
2. **测试集没有声明输出 Schema / 模板**。因此 `format_compliance` 以**该任务隐含
   要求的输出形态**为尺度：结构是否自洽、层次是否清晰、关键信息是否可直接提取。
   不要因为它"没符合一个不存在的 Schema"而扣分。

---

## 三、被测用例

- `{config.DATA_ID_KEY}`: {data_id}
- `{config.DIMENSION_KEY}`: {dimension}
- `{config.KIND_KEY}`: {kind}

### 3.1 任务要求（喂给被测 Agent 的输入原文）

{record.get(config.INPUT_KEY)}

### 3.2 环境声明（precondition，**被测 Agent 看不到这段**）

{precondition}

### 3.3 期望输出（`expected_output`，共 {len(expected)} 项，逐项判定）

{_bullets(expected)}

---

## 四、被测 Agent 的实际输出（证据）

**来源**：{evidence_source}

```text
{evidence if evidence else "（无输出）"}
```

---

## 五、执行元数据

**仅供参考，不得作为打分依据。** 特别地：`{config.RUN_TIMED_OUT}` 为 true 说明输出
可能被中途 kill 而截断，这与 Agent 自己交差了事是两回事——但不要拿秒数之类去脑补分数。

{_meta_block(meta)}

---

## 六、环境参照

该会话真正的工作目录（cwd）是：

```text
{workspace_dir or "（未知）"}
```

任务要求里的路径是绝对路径。**请用它交叉验证**：如果 Agent 声称"目标路径不存在"
或"环境没就绪"，结合上面这个 cwd 判断该说法是否属实，据此定 `{config.ANS_RUN_VALID}`。

---

## 七、你要输出的 JSON

字段含义：

- `{config.ANS_RUN_VALID}`（布尔）：**本次执行环境是否如 3.2 所述就绪，Agent 是否
  真的有机会完成任务。** 任务正常完成 → true；Agent 报告目标路径/依赖不存在而
  3.2 声称其存在、或环境明显缺失导致任务无法进行 → false。判 false 时必须填
  `{config.ANS_INVALID_REASON}`。
  **注意：`{config.ANS_RUN_VALID}` 为 false 时，四个维度分仍然要照常给**——
  下游会把它单列、不计入平均值，但分数本身是"这批为什么无效"的证据。
- `{config.ANS_ITEMS}`（数组）：**必须与 3.3 逐项等长同序**（共 {len(expected)} 项）。
  `text` 原样抄回 3.3 的对应项。
- 四个维度分：`{config.DIMENSIONS[0]}` / `{config.DIMENSIONS[1]}` /
  `{config.DIMENSIONS[2]}` / `{config.DIMENSIONS[3]}`，各为 **{config.SCORE_MIN}~{config.SCORE_MAX}
  的整数**。
  **加权总分与是否通过由下游计算，你不要给这两个数。**
- `{config.ANS_REASONING}`（字符串）：四维打分的整体理由。

逐项判定取值：

{verdict_rules}

```json
{_answer_schema(expected, str(record.get(config.DATA_ID_KEY)))}
```

---

## 八、落盘

用 Write 工具把上述 JSON（**只有 JSON，没有别的**）写到：

```text
{ANSWER_PATH_PLACEHOLDER}
```
"""


def render_case_prompt(record: dict, index: int, answer_path: Path) -> str:
    """组装一条用例的完整 prompt，并把落盘路径填进去。"""
    expected = common.expected_output_of(record, index)
    evidence, source = common.load_evidence(record)
    text = build_prompt(record, expected, evidence, source,
                        common.workspace_dir_of(record))
    return text.replace(ANSWER_PATH_PLACEHOLDER, str(Path(answer_path).resolve()))
