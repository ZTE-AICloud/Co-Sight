#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config.py — e2e-test-evaluator 的全部常量与契约定义。

本模块是唯一的"配置面"：路径形态、权重与阈值、评分 schema 的键名、并发上下限
均在此定义。其余脚本一律 import 本模块，不得就地写魔法数字或字面量。

权重与阈值是**评分算术的唯一真相源**——`tests/test_aggregate.py` 会反向解析
references/runtime-rubric.md 断言二者一致，改了 rubric 却忘了改这里，测试会红。
"""

# ============================== 版本 ==============================

TOOL_VERSION = "e2e-test-evaluator/0.1.0"

# ============================== 路径形态 ==============================

# 默认探测根：<cwd>/outputs/ 下按目录名倒序找 e2e-test*（相对调用方 cwd）。
RUN_PARENT_DIR = "outputs"
RUN_DIR_GLOB = "e2e-test*"

# 输入侧目录名：e2e-test-runner 的交付目录（--input 探测用）
INPUT_ARTIFACT_DIRNAME = "run_datasets"
# 输出侧目录名：本 skill 的交付目录，位于 --output 指向的 run 目录之下
OUTPUT_ARTIFACT_DIRNAME = "eval_datasets"
# 生成器交付目录名。--input 指到它时给专门报错：那是没跑过的用例，评不了。
GENERATOR_ARTIFACT_DIRNAME = "generated_datasets"

SEED_FILENAME = "seed.jsonl"
# 输入侧 runner 的环境记录（取 agent_root 用，仅用于守卫）
RUN_MANIFEST_FILENAME = "run-manifest.json"
AGENT_ROOT_KEY = "agent_root"

# 评分细则：随 skill 分发，是唯一生效版本（不读仓库根的那份）。
# 单文件副本换来了自包含——cwd 怎么切、换到哪台机器都不影响。
RUBRIC_RELPATH = ("references", "runtime-rubric.md")

# --input 指向目录时的探测顺序（先命中者胜）。
# 注意与 runner 的差异：runner 排第一的是 generated_datasets/，这里排第一的必须是
# run_datasets/——顺序反了会读到**没跑过**的那份 seed。
SEED_PROBE_RELPATHS = (
    (INPUT_ARTIFACT_DIRNAME, SEED_FILENAME),
    (SEED_FILENAME,),
)

# ============================== 数据契约（seed.jsonl） ==============================

DATA_ID_KEY = "data_id"                  # 用例唯一标识
INPUT_KEY = "input"                      # 任务要求
PRECONDITION_KEY = "precondition"        # 环境声明。给裁判（判 run_valid 的依据），
                                         # 与 runner 刻意不给被测 agent 的做法相反
EXPECTED_OUTPUT_KEY = "expected_output"  # 判据，字符串列表
DIMENSION_KEY = "dimension"
KIND_KEY = "kind"
RUN_KEY = "run"                          # runner 写入的执行结果
EVAL_KEY = "eval"                        # 本 skill 写入的评分子对象

# run 子对象的键（只读，用于取证据与执行元数据）
RUN_STATUS = "status"
RUN_EXIT_CODE = "exit_code"
RUN_ELAPSED = "elapsed_seconds"
RUN_TIMED_OUT = "timed_out"
RUN_RESULT_PREVIEW = "result_preview"
RUN_CASE_DIR = "case_dir"
RUN_WORKSPACE_DIR = "workspace_dir"
RUN_ERROR = "error"

# 状态取值（runner 定义）
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_TIMEOUT = "timeout"

# 用例目录下的证据文件
CASE_RESULT = "result.json"
WORKSPACE_DIRNAME = "workspace"

# result.json 三种形态的判别键（见 runner SKILL.md）
RESULT_FULL_KEY = "result"               # 合法 JSON：claude 的完整输出
RESULT_PARTIAL_FLAG = "partial_result"   # 超时被 kill：半截 JSON
RESULT_PARTIAL_TEXT = "extracted_text"
RESULT_PARSE_ERROR_FLAG = "parse_error"  # 无法解析
RESULT_PARSE_RAW = "raw"

# ============================== 裁判产物 ==============================

WORK_DIRNAME = ".work"
PROMPT_SUFFIX = ".prompt.md"
ANSWER_SUFFIX = ".answer.json"
# 自愈计数：同一条用例最多派裁判 MAX_JUDGE_ATTEMPTS 次，防"校验失败 → 重派"死循环
ATTEMPTS_SUFFIX = ".attempts"
MAX_JUDGE_ATTEMPTS = 2

# 裁判答案 schema
ANS_RUN_VALID = "run_valid"
ANS_INVALID_REASON = "invalid_reason"
ANS_ITEMS = "items"
ANS_ITEM_TEXT = "text"
ANS_ITEM_VERDICT = "verdict"
ANS_ITEM_NOTE = "note"
ANS_REASONING = "reasoning"

DIMENSIONS = ("correctness", "completeness", "format_compliance", "actionability")

VERDICT_HIT = "hit"
VERDICT_MISS = "miss"
VERDICT_UNVERIFIABLE = "unverifiable"
VERDICTS = (VERDICT_HIT, VERDICT_MISS, VERDICT_UNVERIFIABLE)

# ============================== 评分算术 ==============================
# 权重与阈值在下方硬编码；rubric 里是散文形式（"权重 40%"、"≥ 3.5"）。
# test_aggregate.py 反向解析 rubric 断言一致，漂移即测试红。

DIMENSION_WEIGHTS = {
    "correctness": 0.40,
    "completeness": 0.30,
    "format_compliance": 0.15,
    "actionability": 0.15,
}

SCORE_MIN = 1
SCORE_MAX = 5

THRESHOLD_WEIGHTED = 3.5
THRESHOLD_CORRECTNESS = 3.0
THRESHOLD_COMPLETENESS = 3.0

# completeness 档位表里的命中率下界（rubric 的 ≥80% / ≥60% / ≥30% / <30%）。
# 只用于"命中率与自报分是否明显矛盾"的提示，**不覆盖裁判分数**。
COMPLETENESS_BANDS = ((1.0, 5), (0.8, 4), (0.6, 3), (0.3, 2), (0.0, 1))
# 自报分与档位分相差超过该值才提示
INCONSISTENT_TOLERANCE = 1

# ============================== 产物文件 ==============================

EVAL_MANIFEST_FILENAME = "eval-manifest.json"
REPORT_FILENAME = "report.md"
# 主 agent 把自己的模型标识写在这里；脚本合并进 eval-manifest.json。
# 模型名只有主 agent 知道（脚本猜不准），故由它写、脚本读。
JUDGE_INFO_FILENAME = "judge.json"

# eval 子对象的键
EVAL_STATUS = "status"
EVAL_STATUS_OK = "ok"
EVAL_STATUS_PARSE_ERROR = "parse_error"   # 裁判答案最终仍不可用：单列，不入均值
EVAL_ERROR = "error"
EVAL_RUN_VALID = "run_valid"
EVAL_INVALID_REASON = "invalid_reason"
EVAL_ITEMS = "items"
EVAL_WEIGHTED = "weighted_score"
EVAL_PASSED = "passed"
EVAL_INCONSISTENT = "inconsistent"
EVAL_REASONING = "reasoning"
EVAL_ATTEMPTS = "attempts"

# ============================== 执行参数 ==============================

DEFAULT_CONCURRENCY = 1
MIN_CONCURRENCY = 1
MAX_CONCURRENCY = 32

# data_id 用作文件名，禁止出现路径分隔符或跳转段
FORBIDDEN_CASE_ID_PARTS = ("/", "\\", "..")
